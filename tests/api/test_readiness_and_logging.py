"""T18: /livez, /readyz, the deprecated /healthz alias, supervised broadcast iterations, JSON logs."""

from __future__ import annotations

import asyncio
import json
import logging

import pytest
import pytest_asyncio
from sqlalchemy import text

import api.auth as auth_module
from api import config
from api.logging_config import JSONFormatter, setup_api_logging
from api.main import app
from api.middleware.request_id import request_id_var
from api.routes import health_routes
from api.services import live_broadcast_service as lbs
from api.supervisor import Supervisor
from database import get_db


async def _noop_tick() -> None:
    return None


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("READYZ_CHECK_SCHEMA", "REDIS_URL", "TICK_TIMEOUT_S"):
        monkeypatch.delenv(name, raising=False)


@pytest_asyncio.fixture
async def sup(monkeypatch):
    """A private supervisor swapped in for the one /readyz reads, with a controllable wall clock."""
    clock = {"t": 10_000.0}
    s = Supervisor(clock=lambda: clock["t"], backoff_initial_s=0.01, backoff_max_s=0.02)
    s.fake_clock = clock
    monkeypatch.setattr(health_routes, "supervisor", s)
    yield s
    await s.shutdown(1)


async def _start_healthy(sup: Supervisor, interval: float = 3.0) -> None:
    sup.start("broadcast", _noop_tick, interval_s=interval, tick_timeout_s=1)
    for _ in range(200):
        if sup.state("broadcast").last_success is not None:
            return
        await asyncio.sleep(0.005)
    raise AssertionError("loop never ticked")


@pytest.fixture
def head_in_db(session_maker):
    """Make the test database look migrated: alembic_version = the repository's head revision."""

    async def _set(revision: str | None = None) -> str:
        head = health_routes._alembic_head()
        async with session_maker() as s:
            await s.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
            await s.execute(text("DELETE FROM alembic_version"))
            await s.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": revision or head})
            await s.commit()
        return head

    return _set


# ----------------------------------------------------------------------------- /livez
async def test_livez_has_no_dependencies(client):
    r = await client.get("/livez")  # no auth header, no database
    assert r.status_code == 200 and r.json() == {"status": "alive"}


async def test_livez_is_not_rate_limited(client, monkeypatch):
    from api.rate_limit import limiter

    limiter.enabled = True
    limiter.reset()
    monkeypatch.setenv("RATE_LIMIT_GENERAL", "1/minute")
    try:
        codes = [(await client.get(p)).status_code for p in ("/livez", "/livez", "/readyz", "/readyz")]
    finally:
        limiter.reset()
        limiter.enabled = False
    assert 429 not in codes


async def test_healthz_is_kept_as_a_deprecated_alias(client):
    assert (await client.get("/healthz")).status_code == 200
    schema = app.openapi()["paths"]["/healthz"]["get"]
    assert schema.get("deprecated") is True


# ----------------------------------------------------------------------------- /readyz
async def test_readyz_200_when_db_schema_and_heartbeat_are_ok(client, sup, head_in_db):
    await head_in_db()
    await _start_healthy(sup)
    r = await client.get("/readyz")
    body = r.json()
    assert r.status_code == 200, body
    assert body["status"] == "ready"
    assert body["checks"] == {"database": "ok", "schema": "ok", "broadcast": "ok"}
    assert body["broadcast_restarts"] == 0


async def test_readyz_503_when_the_database_is_down_but_livez_is_200(client, sup):
    await _start_healthy(sup)

    class BrokenSession:
        async def execute(self, *a, **k):
            raise ConnectionError("password=hunter2 host=10.0.0.5 database is down")

    async def broken_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = broken_db
    live, ready = await client.get("/livez"), await client.get("/readyz")
    assert live.status_code == 200
    assert ready.status_code == 503
    body = ready.json()
    assert body["status"] == "not_ready" and body["checks"]["database"] == "fail"
    assert body["checks"]["schema"] == "unknown"
    assert "hunter2" not in ready.text and "10.0.0.5" not in ready.text  # statuses only, no exception text


async def test_readyz_503_when_the_schema_is_behind_head(client, sup, head_in_db):
    await head_in_db("20250222000000")
    await _start_healthy(sup)
    r = await client.get("/readyz")
    assert r.status_code == 503 and r.json()["checks"]["schema"] == "behind"


async def test_readyz_503_when_the_database_was_never_migrated(client, sup):
    await _start_healthy(sup)  # create_all database: no alembic_version table
    r = await client.get("/readyz")
    assert r.status_code == 503 and r.json()["checks"]["schema"] == "missing"


async def test_readyz_schema_check_can_be_switched_off_for_dev_databases(client, sup, monkeypatch):
    monkeypatch.setenv("READYZ_CHECK_SCHEMA", "false")
    await _start_healthy(sup)
    r = await client.get("/readyz")
    assert r.status_code == 200 and r.json()["checks"]["schema"] == "skipped"


async def test_stalled_tick_makes_readyz_503(client, sup, monkeypatch):
    """A tick that hangs never completes a success; once the heartbeat is older than 3 x tick + 5 s, /readyz fails."""
    monkeypatch.setenv("READYZ_CHECK_SCHEMA", "false")
    hung = asyncio.Event()

    async def hanging_tick():
        hung.set()
        await asyncio.sleep(60)

    sup.start("broadcast", hanging_tick, interval_s=3.0, tick_timeout_s=60)
    await asyncio.wait_for(hung.wait(), 1)
    fresh = await client.get("/readyz")  # just started: inside the grace period
    assert fresh.status_code == 200
    sup.fake_clock["t"] += 3 * 3.0 + 5.1  # heartbeat is now stale
    r = await client.get("/readyz")
    assert r.status_code == 503 and r.json()["checks"]["broadcast"] == "stale"
    assert r.json()["broadcast_heartbeat_age_s"] > 14


async def test_readyz_503_when_the_supervisor_gave_up(client, sup, monkeypatch):
    monkeypatch.setenv("READYZ_CHECK_SCHEMA", "false")
    monkeypatch.setenv("SUPERVISOR_MAX_RESTARTS", "1")

    async def always_fails():
        raise RuntimeError("x")

    task = sup.start("broadcast", always_fails, interval_s=0.001, tick_timeout_s=1)
    await asyncio.wait_for(task, 3)
    r = await client.get("/readyz")
    assert r.status_code == 503 and r.json()["checks"]["broadcast"] == "gave_up"


async def test_readyz_503_when_the_loop_was_never_started(client, sup, monkeypatch):
    monkeypatch.setenv("READYZ_CHECK_SCHEMA", "false")
    r = await client.get("/readyz")
    assert r.status_code == 503 and r.json()["checks"]["broadcast"] == "not_running"


async def test_redis_and_model_state_are_degraded_but_do_not_fail_readiness(client, sup, head_in_db, monkeypatch):
    await head_in_db()
    await _start_healthy(sup)
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")  # nothing listens on port 1
    monkeypatch.setattr(health_routes.optimization_service, "get_optimizer", lambda: None)
    r = await client.get("/readyz")
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ready"
    assert {"redis", "optimizer"} <= set(body["degraded"])
    assert body["components"]["redis"] == "degraded" and body["components"]["optimizer"] == "not_loaded"


async def test_unconfigured_redis_is_reported_not_degraded(client, sup, head_in_db):
    await head_in_db()
    await _start_healthy(sup)
    body = (await client.get("/readyz")).json()
    assert body["components"]["redis"] == "not_configured" and "redis" not in body["degraded"]


# ----------------------------------------------------------------------------- the supervised broadcast iteration
async def test_idle_iteration_still_refreshes_the_heartbeat_and_does_not_tick(monkeypatch):
    ticks = []

    async def fake_tick():
        ticks.append(1)
        return {}

    monkeypatch.setattr(lbs, "_tick", fake_tick)
    monkeypatch.setattr(lbs, "manager", lbs.ConnectionManager())
    s = Supervisor()
    s.start("idle-test", lbs.broadcast_once, interval_s=0.01, tick_timeout_s=1)
    for _ in range(200):
        if s.state("idle-test").last_success is not None:
            break
        await asyncio.sleep(0.005)
    assert s.state("idle-test").last_success is not None and ticks == []
    await s.shutdown(1)


async def test_a_failing_tick_is_restarted_by_the_supervisor_not_swallowed(monkeypatch):
    calls = {"n": 0}

    async def flaky_tick():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("tick bug")
        return {"pue": 1.2}

    class FakeWS:
        def __init__(self):
            self.received = []

        async def send_json(self, payload):
            self.received.append(payload)

    manager = lbs.ConnectionManager()
    ws = FakeWS()
    manager.connect(ws)
    monkeypatch.setattr(lbs, "_tick", flaky_tick)
    monkeypatch.setattr(lbs, "manager", manager)
    s = Supervisor(backoff_initial_s=0.01, backoff_max_s=0.02)
    s.start("flaky-test", lbs.broadcast_once, interval_s=0.01, tick_timeout_s=1)
    for _ in range(300):
        if ws.received:
            break
        await asyncio.sleep(0.005)
    assert s.state("flaky-test").restarts == 1 and ws.received[0] == {"pue": 1.2}
    await s.shutdown(1)


# ----------------------------------------------------------------------------- JSON logs
class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.setFormatter(JSONFormatter())
        self.lines: list[dict] = []

    def emit(self, record):
        self.lines.append(json.loads(self.format(record)))


@pytest.fixture
def access_lines():
    handler = _Capture()
    logger = logging.getLogger("api.access")
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.INFO)
    yield handler.lines
    logger.removeHandler(handler)
    logger.setLevel(previous)


async def test_access_log_line_has_request_id_route_status_user_id_duration(client, viewer_headers, access_lines):
    r = await client.get("/api/state", headers={**viewer_headers, "X-Request-ID": "trace-abc-12345"})
    assert r.status_code == 200
    token = viewer_headers["Authorization"].split()[1]
    expected_user = str(auth_module.decode_token(token)["sub"])
    line = next(entry for entry in access_lines if entry.get("route") == "/api/state")
    assert line["request_id"] == "trace-abc-12345"
    assert line["status"] == 200
    assert line["user_id"] == expected_user
    assert isinstance(line["duration_ms"], (int, float)) and line["duration_ms"] >= 0
    assert line["logger"] == "api.access" and {"timestamp", "level", "message"} <= set(line)


async def test_unauthenticated_request_logs_no_user_id(client, access_lines):
    await client.get("/api/state")
    line = next(entry for entry in access_lines if entry.get("route") == "/api/state")
    assert line["status"] in (401, 403) and line["user_id"] is None


async def test_forged_token_is_not_logged_as_a_user(client, access_lines):
    await client.get("/api/state", headers={"Authorization": "Bearer not.a.jwt"})
    line = next(entry for entry in access_lines if entry.get("route") == "/api/state")
    assert line["user_id"] is None


def test_json_formatter_adds_request_id_to_src_loggers_via_contextvar():
    handler = _Capture()
    src_logger = logging.getLogger("src.t18_probe")
    src_logger.addHandler(handler)
    src_logger.setLevel(logging.INFO)
    token = request_id_var.set("ctx-request-12345")
    try:
        src_logger.info("from the ML layer")
    finally:
        request_id_var.reset(token)
        src_logger.removeHandler(handler)
    assert handler.lines[0]["request_id"] == "ctx-request-12345" and handler.lines[0]["logger"] == "src.t18_probe"


def test_setup_api_logging_puts_json_on_both_api_and_src():
    saved = {
        n: (logging.getLogger(n).handlers[:], logging.getLogger(n).propagate, logging.getLogger(n).level)
        for n in ("api", "src")
    }
    try:
        setup_api_logging()
        for name in ("api", "src"):
            logger = logging.getLogger(name)
            assert len(logger.handlers) == 1 and isinstance(logger.handlers[0].formatter, JSONFormatter)
            assert logger.propagate is False
    finally:
        for name, (handlers, propagate, level) in saved.items():
            logger = logging.getLogger(name)
            logger.handlers[:] = handlers
            logger.propagate, logger.level = propagate, level


def test_runtime_config_defaults():
    assert config.tick_timeout_s() == 10.0
    assert config.supervisor_max_restarts() == 10 and config.supervisor_restart_window_s() == 600.0
    assert config.shutdown_deadline_s() == 10.0
