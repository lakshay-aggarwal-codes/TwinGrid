"""T14: one error model (application/problem+json) and bounded cost on compute-heavy routes."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import threading
from pathlib import Path

import httpx
import pytest
from fastapi import APIRouter
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from api import config, rate_limit
from api.errors import ApiError, ErrorBoundaryMiddleware, register_exception_handlers
from api.main import app
from api.middleware.body_limit import BodyLimitMiddleware
from api.middleware.request_id import RequestIDMiddleware
from api.rate_limit import limiter
from api.services import optimization_service, twin_service

LEAKY = "/srv/app/secret_module.py line 12: SELECT * FROM users WHERE password = 'hunter2' -- Traceback"
ENV_NAMES = [env for env, _ in config.RATE_LIMIT_DEFAULTS.values()] + [
    "MAX_BODY_BYTES",
    "COMPUTE_TIMEOUT_S",
    "MAX_CONCURRENT_COMPUTE",
    "HTTP_LIMITS_ENABLED",
    "MAX_QUERY_STRING_CHARS",
]
BASE_KEYS = {"type", "title", "status", "detail", "instance", "request_id"}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    rate_limit._reset_compute_guard()
    yield
    rate_limit._reset_compute_guard()


@pytest.fixture
def probe_routes():
    """Temporary routes on the REAL app, so they pass through the real middleware stack and handlers."""
    router = APIRouter()

    @router.get("/__t14/boom")
    async def boom():
        raise RuntimeError(LEAKY)

    @router.get("/__t14/conflict")
    async def conflict():
        raise ApiError(409, "conflict", "Already exists")

    @router.get("/__t14/unavailable")
    async def unavailable():
        raise ApiError(503, "model_unavailable", "No model")

    @router.get("/__t14/timeout")
    async def timeout():
        raise ApiError(504, "compute_timeout", "Too slow")

    @router.get("/__t14/typed")
    async def typed(n: int, k: int = 5):
        return {"n": n, "k": k}

    before = len(app.router.routes)
    app.include_router(router)
    added = app.router.routes[before:]
    yield
    for route in added:
        app.router.routes.remove(route)


@pytest.fixture
def limits_on(client):
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.reset()
    limiter.enabled = False


def assert_problem(r: httpx.Response, status: int, code: str | None = None, path: str | None = None) -> dict:
    assert r.status_code == status, r.text
    assert r.headers["content-type"].split(";")[0] == "application/problem+json"
    body = r.json()
    expected_keys = BASE_KEYS | ({"errors"} if status == 422 else set())
    assert set(body) == expected_keys, set(body) ^ expected_keys
    assert body["status"] == status
    assert isinstance(body["detail"], str) and body["detail"]
    assert isinstance(body["title"], str) and body["title"]
    assert re.fullmatch(r"urn:twingrid:error:[a-z_]+", body["type"])
    if code:
        assert body["type"] == f"urn:twingrid:error:{code}"
    if path:
        assert body["instance"] == path
    assert body["request_id"] and body["request_id"] == r.headers["X-Request-ID"]
    return body


# ----------------------------------------------------------------------------- schema, one case per status
async def test_401_is_problem_json(client):
    r = await client.get("/api/state", headers={"Authorization": "Bearer not-a-token"})
    assert_problem(r, 401, "unauthorized", "/api/state")


async def test_403_is_problem_json(client, viewer_headers):
    r = await client.post("/api/optimize", json={}, headers=viewer_headers)
    body = assert_problem(r, 403, "forbidden")
    assert "Operator role required" in body["detail"]  # detail stays the primary human string


async def test_404_is_problem_json(client):
    assert_problem(await client.get("/api/does-not-exist"), 404, "not_found", "/api/does-not-exist")


async def test_405_is_problem_json_and_keeps_allow_header(client):
    r = await client.post("/healthz")
    assert_problem(r, 405, "method_not_allowed")
    assert "GET" in r.headers["allow"]


async def test_409_is_problem_json(client, probe_routes):
    assert_problem(await client.get("/__t14/conflict"), 409, "conflict")


async def test_413_oversize_body_is_problem_json(client, viewer_headers, monkeypatch):
    monkeypatch.setenv("MAX_BODY_BYTES", "100")
    r = await client.post("/api/optimize", json={"padding": "x" * 500}, headers=viewer_headers)
    assert_problem(r, 413, "payload_too_large", "/api/optimize")


async def test_413_oversize_query_string_is_problem_json(client, viewer_headers, monkeypatch):
    monkeypatch.setenv("MAX_QUERY_STRING_CHARS", "100")
    r = await client.get("/api/state", params={"padding": "x" * 200}, headers=viewer_headers)
    assert_problem(r, 413, "payload_too_large")


async def test_422_keeps_status_loc_msg_type_and_drops_input_and_ctx(client, viewer_headers):
    r = await client.get("/api/state", params={"utilisation": "7.25"}, headers=viewer_headers)
    body = assert_problem(r, 422, "validation_error")
    assert body["errors"], "422 must list its errors"
    for err in body["errors"]:
        assert set(err) == {"loc", "msg", "type"}
        assert "input" not in err and "ctx" not in err
    assert body["errors"][0]["loc"] == ["query", "utilisation"]
    assert "7.25" not in r.text  # the caller's raw value is not echoed
    assert "utilisation" in body["detail"]  # one-line string summary for clients that only read `detail`


async def test_422_for_a_json_body_does_not_echo_the_body(client, operator_headers):
    r = await client.post("/api/optimize", json={"alpha": 1234.5678}, headers=operator_headers)
    assert_problem(r, 422)
    assert "1234.5678" not in r.text and '"input"' not in r.text and '"ctx"' not in r.text


async def test_429_is_problem_json_with_retry_after(client, viewer_headers, limits_on, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_STATE", "1/minute")
    assert (await client.get("/api/state", headers=viewer_headers)).status_code == 200
    r = await client.get("/api/state", headers=viewer_headers)
    assert_problem(r, 429, "rate_limited")
    assert int(r.headers["Retry-After"]) >= 1
    assert "Rate limit exceeded" in r.json()["detail"]


async def test_500_is_generic_and_discloses_nothing(client, probe_routes, caplog):
    with caplog.at_level("ERROR"):
        r = await client.get("/__t14/boom")
    body = assert_problem(r, 500, "internal_error", "/__t14/boom")
    assert body["detail"] == "Internal server error"
    for fragment in ("/srv", "secret_module", "SELECT", "hunter2", "Traceback", "RuntimeError", ".py"):
        assert fragment not in r.text
    # ... but the real cause is in the server log, tagged with the same request id
    assert any(LEAKY in (rec.exc_text or "") or LEAKY in rec.getMessage() or rec.exc_info for rec in caplog.records)
    assert any(body["request_id"] in rec.getMessage() for rec in caplog.records)


async def test_503_model_unavailable_when_no_verified_model_and_never_trains(
    client, operator_headers, monkeypatch, session_maker, count_rows
):
    async def no_model(*a, **k):
        return None

    def must_not_train(*a, **k):
        raise AssertionError("must not train in a request")

    monkeypatch.setattr(optimization_service, "_ensure_optimizer", no_model)
    monkeypatch.setattr(optimization_service.JointOptimizer, "train", must_not_train)
    r = await client.post("/api/optimize", json={}, headers=operator_headers)
    body = assert_problem(r, 503, "model_unavailable")
    assert "model" in body["detail"].lower()
    from models.db_models import OptimizationResult

    assert await count_rows(OptimizationResult) == 0  # nothing persisted for a failed optimize


async def test_503_generic_code(client, probe_routes):
    assert_problem(await client.get("/__t14/unavailable"), 503, "model_unavailable")


async def test_504_is_problem_json(client, probe_routes):
    assert_problem(await client.get("/__t14/timeout"), 504, "compute_timeout")


# ----------------------------------------------------------------------------- request id
@pytest.mark.parametrize("rid", ["abc-12345", "A.b_c-d.e1234", "x" * 64])
async def test_valid_request_id_is_echoed(client, rid):
    r = await client.get("/healthz", headers={"X-Request-ID": rid})
    assert r.headers["X-Request-ID"] == rid


@pytest.mark.parametrize(
    "rid", ["short", "has space in it", "x" * 65, "bad;chars!!!!", "semi;colon;12345", "unicode-é-12345"]
)
async def test_invalid_request_id_is_replaced_by_a_uuid(client, rid):
    try:
        r = await client.get("/healthz", headers={"X-Request-ID": rid})
    except (UnicodeEncodeError, httpx.InvalidURL):
        pytest.skip("client refuses to send that header")  # pragma: no cover
    got = r.headers["X-Request-ID"]
    assert got != rid
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", got)


# ----------------------------------------------------------------------------- limits
async def test_limit_exempt_probe_is_never_limited(client, limits_on, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_GENERAL", "1/minute")
    codes = [(await client.get("/healthz")).status_code for _ in range(4)]
    assert 429 not in codes


async def test_general_limit_covers_routes_without_their_own_scope(client, viewer_headers, limits_on, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_GENERAL", "2/minute")
    codes = [(await client.get("/api/alerts", headers=viewer_headers)).status_code for _ in range(3)]
    assert codes[:2] == [200, 200] and codes[2] == 429


async def test_http_limits_enabled_false_is_the_rollback_switch(client, viewer_headers, limits_on, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_STATE", "1/minute")
    monkeypatch.setenv("HTTP_LIMITS_ENABLED", "false")
    codes = [(await client.get("/api/state", headers=viewer_headers)).status_code for _ in range(3)]
    assert codes == [200, 200, 200]


# ----------------------------------------------------------------------------- compute guard
async def test_heavy_route_is_429_when_the_concurrency_bound_is_reached(client, viewer_headers, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_COMPUTE", "1")
    started, release = threading.Event(), threading.Event()

    def slow_whatif(*args):
        started.set()
        release.wait(5)
        return {"pue": 1.2}

    monkeypatch.setattr(twin_service, "compute_whatif", slow_whatif)
    first = asyncio.create_task(client.get("/api/whatif", headers=viewer_headers))
    for _ in range(100):
        if started.is_set():
            break
        await asyncio.sleep(0.02)
    assert started.is_set()
    second = await client.get("/api/whatif", headers=viewer_headers)
    body = assert_problem(second, 429, "compute_busy")
    assert second.headers["Retry-After"] == "1" and "compute" in body["detail"].lower()
    release.set()
    assert (await first).status_code == 200
    assert rate_limit.compute_in_flight() == 0
    assert (await client.get("/api/whatif", headers=viewer_headers)).status_code == 200


async def test_timeout_returns_504_and_the_slot_is_released_when_the_work_finishes(client, viewer_headers, monkeypatch):
    monkeypatch.setenv("COMPUTE_TIMEOUT_S", "0.1")
    monkeypatch.setenv("MAX_CONCURRENT_COMPUTE", "1")
    done = threading.Event()

    def slow_whatif(*args):
        done.wait(0.5)  # outlives the 0.1 s budget; a thread cannot be cancelled
        return {"pue": 1.2}

    monkeypatch.setattr(twin_service, "compute_whatif", slow_whatif)
    r = await client.get("/api/whatif", headers=viewer_headers)
    assert_problem(r, 504, "compute_timeout")
    # the thread is still running, so the slot is still held (the bound stays true) ...
    assert rate_limit.compute_in_flight() == 1
    for _ in range(100):  # ... and is released as soon as it ends
        if rate_limit.compute_in_flight() == 0:
            break
        await asyncio.sleep(0.02)
    assert rate_limit.compute_in_flight() == 0
    monkeypatch.setattr(twin_service, "compute_whatif", lambda *a: {"pue": 1.1})
    assert (await client.get("/api/whatif", headers=viewer_headers)).status_code == 200


async def test_async_compute_timeout_cancels_and_releases_the_slot(monkeypatch):
    monkeypatch.setenv("COMPUTE_TIMEOUT_S", "0.05")
    cancelled = asyncio.Event()

    async def forever():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with pytest.raises(ApiError) as exc:
        await rate_limit.run_compute_async(forever)
    assert exc.value.status_code == 504
    assert cancelled.is_set() and rate_limit.compute_in_flight() == 0


async def test_compute_exception_releases_the_slot(monkeypatch):
    def boom():
        raise ValueError("x")

    with pytest.raises(ValueError):
        await rate_limit.run_compute(boom)
    assert rate_limit.compute_in_flight() == 0


# ----------------------------------------------------------------------------- body cap, ASGI level
def _mini_app(max_bytes: int, monkeypatch) -> Starlette:
    monkeypatch.setenv("MAX_BODY_BYTES", str(max_bytes))

    async def echo(request: Request):
        return JSONResponse({"n": len(await request.body())})

    mini = Starlette(routes=[Route("/echo", echo, methods=["POST"])])
    register_exception_handlers(mini)
    mini.add_middleware(BodyLimitMiddleware)
    mini.add_middleware(ErrorBoundaryMiddleware)
    mini.add_middleware(RequestIDMiddleware)
    return mini


async def test_streamed_body_without_content_length_is_cut_off_with_413(monkeypatch):
    mini = _mini_app(100, monkeypatch)

    async def chunks():
        for _ in range(10):
            yield b"x" * 50

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mini), base_url="http://t") as c:
        r = await c.post("/echo", content=chunks())
        ok = await c.post("/echo", content=b"x" * 100)
    assert_problem(r, 413, "payload_too_large", "/echo")
    assert ok.status_code == 200 and ok.json() == {"n": 100}


# ----------------------------------------------------------------------------- every route carries a limit
def _load_route_controls():
    path = Path(__file__).resolve().parents[2] / "reports" / "postT9" / "T14_route_controls.py"
    spec = importlib.util.spec_from_file_location("t14_route_controls", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_http_route_has_an_http_limit_except_the_probes():
    table = _load_route_controls().rows(app)
    assert table, "no routes found"
    missing = [(r["methods"], r["path"]) for r in table if r["limit"] == "NONE"]
    assert not missing, f"routes without http_limit: {missing}"
    assert any(r["limit"].startswith("exempt") for r in table)  # /healthz


@pytest.mark.parametrize(
    ("method", "path", "scope"),
    [
        ("GET", "/api/state", "state"),
        ("GET", "/api/whatif", "whatif"),
        ("GET", "/api/benchmark", "benchmark"),
        ("GET", "/api/simulate/{hours}", "simulate"),
        ("GET", "/api/anomaly_score", "anomaly_score"),
        ("GET", "/api/esg_report", "esg_report"),
        ("POST", "/api/shadow_mode/sample", "shadow_sample"),
        ("POST", "/api/optimize", "optimize"),
        ("POST", "/api/optimize/train_async", "train_async"),
        ("POST", "/api/alerts/{alert_id}/acknowledge", "alert_ack"),
        ("POST", "/api/webhooks", "webhook"),
        ("DELETE", "/api/webhooks", "webhook"),
    ],
)
def test_heavy_routes_have_their_own_scope(method, path, scope):
    table = _load_route_controls().rows(app)
    row = next(r for r in table if r["path"] == path and method in r["methods"])
    assert scope in row["limit"].split(" + ")


def test_shadow_sample_and_optimize_are_operator_routes():
    table = _load_route_controls().rows(app)
    auth = {(r["methods"], r["path"]): r["auth"] for r in table}
    assert auth[("POST", "/api/shadow_mode/sample")] == "operator"
    assert auth[("POST", "/api/optimize")] == "operator"


def test_problem_body_is_valid_json_text():
    # guards the media type / body pairing used by every handler
    from api.errors import problem_response

    resp = problem_response({"path": "/x", "request_id": "r" * 8}, 404, "nope")
    assert json.loads(resp.body)["type"] == "urn:twingrid:error:not_found"
    assert resp.media_type == "application/problem+json"
