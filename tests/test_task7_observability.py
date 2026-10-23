"""Task 7: structured logs with request ids, redaction in the JSON logger, request-id propagation to queued jobs and
WebSockets, POST /api/client-errors, and the observability overlay files.

The app is exercised through httpx's ASGITransport (no Postgres, no Redis, no Docker).
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-suite-only")
os.environ["ENVIRONMENT"] = "development"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.routing import WebSocketRoute  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import api.auth as auth_module  # noqa: E402
import api.services.anomaly_service  # noqa: E402,F401  (registers its metrics)
import api.services.audit_service  # noqa: E402,F401
import api.services.telemetry_metrics  # noqa: E402,F401
from api.logging_config import JSONFormatter  # noqa: E402
from api.main import app  # noqa: E402
from api.middleware.metrics import registry, render_metrics  # noqa: E402
from api.middleware.request_id import RequestIDMiddleware, request_id_var  # noqa: E402
from api.plugins.client_errors import OUTCOMES, RedactionFilter  # noqa: E402
from api.rate_limit import limiter  # noqa: E402
from src import log_context, task_queue  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OBS = ROOT / "deploy" / "observability"
REPORT = {
    "level": "error",
    "source": "WebSocket",
    "message": "connection failed",
    "page": "/analytics",
    "timestamp": "2026-10-13T09:00:00.000Z",
}
KEY = "report-key-0123456789"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("CLIENT_ERRORS_MAX_BYTES", "CLIENT_ERRORS_RATE_LIMIT", "CLIENT_ERRORS_REPORT_KEY", "METRICS_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    yield
    limiter.reset()


@pytest.fixture
def json_log():
    """Capture the ``api.client_errors`` logger as the API's JSON formatter renders it."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    logger = logging.getLogger("api.client_errors")
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.DEBUG)
    yield stream
    logger.removeHandler(handler)
    logger.setLevel(previous)


@pytest_asyncio.fixture
async def client():
    previous = limiter.enabled
    limiter.enabled = False
    transport = ASGITransport(app=app, raise_app_exceptions=False, client=("10.7.7.7", 5000))
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    limiter.enabled = previous


def _count(outcome: str) -> float:
    return registry.get_sample_value("client_errors_received_total", {"outcome": outcome}) or 0.0


def _post(client, body=None, *, headers=None, params=None, content=None):
    data = json.dumps(REPORT if body is None else body).encode() if content is None else content
    return client.post(
        "/api/client-errors", content=data, params=params, headers={"content-type": "text/plain", **(headers or {})}
    )


# ------------------------------------------------------------------------- JSON logs carry the request id, redacted


def _line(**record_kwargs) -> dict:
    record = logging.LogRecord(
        "api.test", logging.INFO, __file__, 1, record_kwargs.pop("msg"), (), record_kwargs.pop("exc_info", None)
    )
    return json.loads(JSONFormatter().format(record))


def test_every_log_line_carries_the_request_id_of_the_request_being_served():
    token = request_id_var.set("req-abc-12345")
    try:
        assert _line(msg="hello")["request_id"] == "req-abc-12345"
    finally:
        request_id_var.reset(token)
    assert _line(msg="outside a request")["request_id"] == "-"


def test_the_json_logger_redacts_passwords_tokens_tickets_refresh_tokens_and_authorization():
    secrets = ["hunter2-hunter2", "TICKETVALUE123", "REFRESHVALUE1", "ACCESSVALUE12", "opaque.credential-1"]
    msg = (
        'login {"password": "hunter2-hunter2"} /ws/live?ticket=TICKETVALUE123&access_token=ACCESSVALUE12 '
        "refresh_token=REFRESHVALUE1 Authorization: Bearer opaque.credential-1"
    )
    out = json.dumps(_line(msg=msg))
    for secret in secrets:
        assert secret not in out
    assert "[REDACTED]" in out
    assert "login" in out  # the rest of the line survives


def test_exception_text_is_redacted_too():
    try:
        raise RuntimeError("upstream said password=hunter2-hunter2")
    except RuntimeError:
        import sys

        rendered = _line(msg="boom", exc_info=sys.exc_info())
    assert "hunter2-hunter2" not in json.dumps(rendered)
    assert "RuntimeError" in rendered["exception"]


def test_the_server_access_log_filter_hides_the_report_key_and_tokens():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s" %d',
        ("1.2.3.4", "POST", f"/api/client-errors?key={KEY}", 204),
        None,
    )
    RedactionFilter().filter(record)
    assert KEY not in record.getMessage() and "[REDACTED]" in record.getMessage()


# --------------------------------------------------------------- X-Request-ID over HTTP, WebSocket and queued jobs


async def test_x_request_id_is_echoed_when_valid_and_replaced_when_not(client):
    ok = await client.get("/livez", headers={"X-Request-ID": "abcdef-123456"})
    assert ok.headers["x-request-id"] == "abcdef-123456"
    for bad in ("ab", "has space in it", "x" * 65):
        other = await client.get("/livez", headers={"X-Request-ID": bad})
        assert other.headers["x-request-id"] != bad and len(other.headers["x-request-id"]) >= 6


def test_websocket_handlers_see_the_request_id_and_log_with_it():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    logger = logging.getLogger("api.test_ws")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    async def endpoint(websocket):
        await websocket.accept()
        logger.info("ws handler running")
        await websocket.send_json({"request_id": request_id_var.get()})
        await websocket.close()

    asgi = RequestIDMiddleware(Starlette(routes=[WebSocketRoute("/w", endpoint)]))
    with TestClient(asgi).websocket_connect("/w", headers={"X-Request-ID": "ws-req-000001"}) as ws:
        assert ws.receive_json() == {"request_id": "ws-req-000001"}
    assert json.loads(stream.getvalue().splitlines()[0])["request_id"] == "ws-req-000001"


class _FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, func_path, *args, **kwargs):
        self.calls.append((func_path, args, kwargs))
        return SimpleNamespace(id="job-1")


def test_enqueue_attaches_the_current_request_id_as_job_meta(monkeypatch):
    queue = _FakeQueue()
    monkeypatch.setattr(task_queue, "_get_queue", lambda: queue)
    token = request_id_var.set("req-job-000001")
    try:
        assert task_queue.enqueue("src.run_jobs.run_whatif_job", "r1", "s1", {}) == "job-1"
    finally:
        request_id_var.reset(token)
    assert queue.calls[0][2]["meta"] == {"request_id": "req-job-000001"}


def test_enqueue_outside_a_request_adds_no_meta(monkeypatch):
    queue = _FakeQueue()
    monkeypatch.setattr(task_queue, "_get_queue", lambda: queue)
    task_queue.enqueue("src.run_jobs.run_whatif_job", "r1", "s1", {})
    assert "meta" not in queue.calls[0][2]


def test_a_job_runs_with_the_enqueuing_requests_id_and_logs_it(monkeypatch):
    monkeypatch.setattr(log_context, "_current_job", lambda: SimpleNamespace(meta={"request_id": "req-from-api-1"}))
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    logger = logging.getLogger("src.log_context")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    @log_context.with_request_id
    def job():
        return request_id_var.get()

    try:
        assert job() == "req-from-api-1"
    finally:
        logger.removeHandler(handler)
    assert request_id_var.get() == "-"  # restored afterwards
    lines = [json.loads(x) for x in stream.getvalue().splitlines()]
    assert all(line["request_id"] == "req-from-api-1" and "req-from-api-1" in line["message"] for line in lines)
    assert len(lines) == 2  # started, finished


def test_a_failing_job_logs_the_failure_and_still_raises(monkeypatch):
    monkeypatch.setattr(log_context, "_current_job", lambda: SimpleNamespace(meta={"request_id": "req-from-api-1"}))

    @log_context.with_request_id
    def job():
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        job()
    assert request_id_var.get() == "-"


@pytest.mark.parametrize("meta", [None, {}, {"request_id": 5}, {"request_id": "bad id"}])
def test_a_job_without_a_usable_request_id_runs_without_one(monkeypatch, meta):
    monkeypatch.setattr(log_context, "_current_job", lambda: SimpleNamespace(meta=meta))

    @log_context.with_request_id
    def job():
        return request_id_var.get()

    assert job() == "-"


# ------------------------------------------------------------------------------------------ POST /api/client-errors


def test_the_plugin_is_loaded_and_exposes_every_outcome_at_zero_or_more():
    assert any(
        getattr(r, "path", None) == "/api/client-errors" for r in app.routes
    ) or "/api/client-errors" in json.dumps(app.openapi()["paths"])
    text = render_metrics()[0].decode()
    for outcome in OUTCOMES:
        assert f'client_errors_received_total{{outcome="{outcome}"}}' in text


async def test_development_without_a_key_accepts_a_report_counts_it_and_logs_it(client, json_log):
    before = _count("accepted")
    response = await _post(client)
    assert response.status_code == 204 and response.content == b""
    assert _count("accepted") == before + 1
    line = json.loads(json_log.getvalue().splitlines()[0])
    assert line["level"] == "ERROR" and "WebSocket" in line["message"] and "connection failed" in line["message"]


async def test_a_warning_report_is_logged_at_warning_level(client, json_log):
    await _post(client, {**REPORT, "level": "warning"})
    assert json.loads(json_log.getvalue().splitlines()[0])["level"] == "WARNING"


async def test_secrets_inside_a_report_never_reach_the_log(client, json_log):
    body = {
        **REPORT,
        "message": "ws://h/ws/live?token=SECRETONE12 Bearer abc.def.ghi",
        "stack": "at a ?ticket=SECRETTWO12",
    }
    assert (await _post(client, body)).status_code == 204
    out = json_log.getvalue()
    for secret in ("SECRETONE12", "abc.def.ghi", "SECRETTWO12"):
        assert secret not in out
    assert "[REDACTED]" in out


async def test_production_without_a_key_the_endpoint_does_not_exist(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    before = _count("disabled")
    response = await _post(client)
    assert response.status_code == 404
    assert _count("disabled") == before + 1
    assert "Traceback" not in response.text


async def test_with_a_key_a_missing_or_wrong_key_is_401_and_the_right_key_or_a_bearer_token_is_accepted(
    client, monkeypatch, json_log
):
    monkeypatch.setenv("CLIENT_ERRORS_REPORT_KEY", KEY)
    before = _count("unauthorised")
    assert (await _post(client)).status_code == 401
    assert (await _post(client, params={"key": "test-wrong-key-0123456789"})).status_code == 401
    assert (await _post(client, headers={"Authorization": "Bearer not.a.token"})).status_code == 401
    assert _count("unauthorised") == before + 3
    assert json_log.getvalue() == ""  # a refused report writes nothing to the log

    assert (await _post(client, params={"key": KEY})).status_code == 204
    token = auth_module.create_access_token(1, "viewer")
    assert (await _post(client, headers={"Authorization": f"Bearer {token}"})).status_code == 204
    assert KEY not in json_log.getvalue()


async def test_production_with_a_key_accepts_reports(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CLIENT_ERRORS_REPORT_KEY", KEY)
    assert (await _post(client, params={"key": KEY})).status_code == 204


async def test_a_too_short_key_counts_as_no_key(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CLIENT_ERRORS_REPORT_KEY", "short")
    assert (await _post(client, params={"key": "short"})).status_code == 404


async def test_the_default_size_cap_is_8192_bytes(client):
    before = _count("too_large")
    big = {**REPORT, "message": "m" * 9000}
    response = await _post(client, big)
    assert response.status_code == 413
    assert _count("too_large") == before + 1
    assert (await _post(client, {**REPORT, "message": "m" * 400})).status_code == 204


async def test_the_size_cap_is_configurable_and_also_enforced_without_a_content_length(client, monkeypatch):
    monkeypatch.setenv("CLIENT_ERRORS_MAX_BYTES", "300")
    payload = json.dumps({**REPORT, "message": "m" * 400}).encode()

    async def chunks():
        for i in range(0, len(payload), 50):
            yield payload[i : i + 50]

    response = await client.post("/api/client-errors", content=chunks(), headers={"content-type": "text/plain"})
    assert response.status_code == 413


@pytest.mark.parametrize(
    "body",
    [b"not json", b"[]", json.dumps({**REPORT, "level": "fatal"}).encode(), json.dumps({"level": "error"}).encode()],
)
async def test_malformed_reports_are_422_and_counted(client, body):
    before = _count("invalid")
    response = await _post(client, content=body)
    assert response.status_code == 422
    assert _count("invalid") == before + 1
    assert "not json" not in response.text


async def test_over_the_rate_limit_is_429_with_retry_after_per_client_ip(client, monkeypatch):
    monkeypatch.setenv("CLIENT_ERRORS_RATE_LIMIT", "2/minute")
    limiter.enabled = True
    limiter.reset()
    before = _count("rate_limited")
    assert (await _post(client)).status_code == 204
    assert (await _post(client)).status_code == 204
    third = await _post(client)
    assert third.status_code == 429 and int(third.headers["retry-after"]) >= 1
    assert _count("rate_limited") == before + 1


async def test_a_wrong_method_or_get_is_not_a_way_in(client):
    assert (await client.get("/api/client-errors")).status_code == 405


def test_the_reporter_still_sends_the_fields_and_caps_this_endpoint_expects():
    ts = (ROOT / "twin-stream-insight-main" / "src" / "lib" / "errorReporter.ts").read_text(encoding="utf-8")
    for field in ("level", "source", "message", "stack", "page", "timestamp"):
        assert re.search(rf"\b{field}\b", ts), field
    assert "slice(0, 500)" in ts and "slice(0, 2000)" in ts  # the caps src/client_errors.py FIELD_LIMITS mirror
    assert "text/plain" in ts  # no custom headers: that is why the key travels in the URL
    from src.client_errors import FIELD_LIMITS

    assert FIELD_LIMITS["message"] == 500 and FIELD_LIMITS["stack"] == 2000


def test_the_metric_names_other_tasks_depend_on_are_exported_exactly():
    text = render_metrics()[0].decode()
    for name in (
        "telemetry_persist_failures_total",
        "telemetry_retention_deleted_rows_total",
        "client_errors_received_total",
    ):
        assert f"\n{name}" in "\n" + text, name


# ------------------------------------------------------------------------------------- the observability overlay files

METRIC_WORD = re.compile(r"\b(?:http|ws|telemetry|background|anomaly|audit|client_errors|model)_[a-z0-9_]+\b")


def _exported_names() -> set[str]:
    names = {s.name for metric in registry.collect() for s in metric.samples} | {"up"}
    # A labelled metric exports no sample until its first child exists, so whether it shows up would depend on which
    # tests ran before this one; a registered family is exported by definition.
    names |= {m.name + "_total" if m.type == "counter" else m.name for m in registry.collect()}
    return names


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_every_metric_in_the_alert_rules_and_the_dashboard_is_really_exported():
    exported = _exported_names()
    rules = _read(OBS / "prometheus" / "alert_rules.yml")
    exprs = re.findall(r"^\s*expr:\s*(.+)$", rules, flags=re.M)
    dashboard = json.loads(_read(OBS / "grafana" / "dashboards" / "twingrid-overview.json"))
    exprs += [t["expr"] for p in dashboard["panels"] for t in p["targets"]]
    assert len(exprs) >= 15
    used = {name for e in exprs for name in METRIC_WORD.findall(e)} | ({"up"} if "up{" in rules else set())
    assert used and used <= exported, sorted(used - exported)


def test_alert_rules_point_at_runbooks_that_exist_and_say_they_are_unverified():
    rules = _read(OBS / "prometheus" / "alert_rules.yml")
    alerts = re.findall(r"^\s*- alert:\s*(\w+)", rules, flags=re.M)
    runbooks = re.findall(r"runbook:\s*(\S+)", rules)
    assert len(alerts) == len(runbooks) >= 9
    for rel in runbooks:
        assert (ROOT / rel).is_file(), rel
    assert "NOT VERIFIED" in rules and "hypothes" in rules


def test_dashboard_json_is_well_formed():
    dash = json.loads(_read(OBS / "grafana" / "dashboards" / "twingrid-overview.json"))
    ids = [p["id"] for p in dash["panels"]]
    assert len(ids) == len(set(ids)) >= 10 and dash["uid"] == "twingrid-overview"
    assert all(p["datasource"]["uid"] == "prometheus" for p in dash["panels"])


def test_the_overlay_is_opt_in_binds_locally_and_holds_no_secret():
    text = _read(OBS / "docker-compose.observability.yml")
    assert text.count('profiles: ["observability"]') == 2 and 'profiles: ["alerting"]' in text
    ports = re.findall(r'^\s*-\s*"([^"]*:\d+:\d+)"', text, flags=re.M)
    assert ports and all(p.startswith("127.0.0.1:") for p in ports)
    assert "${GRAFANA_ADMIN_PASSWORD:?" in text
    assert not re.search(r"(?i)(password|token|secret)\w*\s*[=:]\s*[\"']?[A-Za-z0-9]{8,}", text)
    base = _read(ROOT / "docker-compose.yml")
    assert "prometheus" not in base and "grafana" not in base  # the default stack stays untouched


def test_prometheus_scrapes_metrics_with_a_bearer_credentials_file():
    cfg = _read(OBS / "prometheus" / "prometheus.yml")
    assert "metrics_path: /metrics" in cfg and "credentials_file:" in cfg and "backend:8000" in cfg
    assert "credentials:" not in cfg.replace("credentials_file:", "")  # never an inline token


def test_every_required_runbook_exists_is_indexed_and_the_slo_page_marks_targets_unmeasured():
    names = (
        "api-down",
        "database-down",
        "stale-feed",
        "migration-failure",
        "high-5xx",
        "artifact-load-failure",
        "rotating-secrets",
    )
    index = _read(ROOT / "docs" / "runbooks" / "README.md")
    for name in names:
        assert (ROOT / "docs" / "runbooks" / f"{name}.md").is_file(), name
        assert f"({name}.md)" in index, name
    slo = _read(ROOT / "docs" / "SLO.md")
    rows = [r for r in slo.splitlines() if r.startswith("| ") and "---" not in r and "Objective" not in r]
    assert len(rows) >= 5 and all("NOT MEASURED" in r for r in rows)
    assert "hypotheses" in slo
