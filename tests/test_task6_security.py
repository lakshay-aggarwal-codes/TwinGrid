"""Task 6: security headers, WebSocket tickets, login lockout, secret redaction, probe/metrics exposure.

Self-contained: the app is exercised through httpx's ASGITransport with an in-memory SQLite database (no Postgres,
no Redis -- a fake Redis-like client stands in where the Redis path matters).
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
import tomllib
from pathlib import Path

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-suite-only")
os.environ["ENVIRONMENT"] = "development"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

import api.auth as auth_module  # noqa: E402
from api.main import app  # noqa: E402
from api.middleware.metrics import render_metrics  # noqa: E402
from api.rate_limit import limiter  # noqa: E402
from api.routes import websocket_routes as ws_routes  # noqa: E402
from api.services import audit_service  # noqa: E402
from api.services.live_broadcast_service import manager  # noqa: E402
from database import get_db  # noqa: E402
from models.db_models import Base, User  # noqa: E402
from src import login_lockout, ws_tickets  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HEADER_NAMES = (
    "x-content-type-options",
    "x-frame-options",
    "content-security-policy",
    "referrer-policy",
    "permissions-policy",
)


# ----------------------------------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in (
        "WS_TICKET_TTL_SECONDS",
        "WS_ALLOW_QUERY_TOKEN",
        "REDIS_URL",
        "TRUST_PROXY_HEADERS",
        "TRUSTED_PROXY_HOPS",
        "METRICS_TOKEN",
        "METRICS_TOKEN_FILE",
        "LOGIN_LOCKOUT_ENABLED",
        "LOGIN_LOCKOUT_THRESHOLD",
        "LOGIN_LOCKOUT_BASE_SECONDS",
        "LOGIN_LOCKOUT_MAX_SECONDS",
        "LOGIN_LOCKOUT_RESET_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("READYZ_CHECK_SCHEMA", "false")
    ws_tickets.set_redis_factory(None)
    ws_tickets.reset_for_tests()
    login_lockout.reset()
    yield
    ws_tickets.set_redis_factory(None)
    ws_tickets.reset_for_tests()
    login_lockout.reset()
    limiter.reset()


@pytest_asyncio.fixture
async def session_maker():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    await engine.dispose()


def _client_factory(session_maker):
    async def override_get_db():
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    audit_service.set_session_factory(session_maker)

    def make(ip: str = "10.1.1.1", base_url: str = "http://test") -> AsyncClient:
        transport = ASGITransport(app=app, raise_app_exceptions=False, client=(ip, 5000))
        return AsyncClient(transport=transport, base_url=base_url)

    return make


@pytest_asyncio.fixture
async def make_client(session_maker):
    previous = limiter.enabled
    limiter.enabled = False
    factory = _client_factory(session_maker)
    yield factory
    app.dependency_overrides.clear()
    audit_service.set_session_factory(None)
    limiter.enabled = previous


@pytest_asyncio.fixture
async def client(make_client):
    async with make_client() as c:
        yield c


async def _user(session_maker, username="alice", password="correct-horse-1", role="viewer") -> User:
    async with session_maker() as s:
        user = User(username=username, hashed_password=auth_module.hash_password(password), role=role)
        s.add(user)
        await s.commit()
        await s.refresh(user)
    return user


def _bearer(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_module.create_access_token(user.id, user.role)}"}


class FakeRedis:
    """The two operations src/ws_tickets uses: ``set(key, value, ex=)`` and a MULTI-style pipeline."""

    def __init__(self):
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.fail = False

    def set(self, key, value, ex=None):
        if self.fail:
            raise ConnectionError("redis://user:pw@10.0.0.9 refused")
        self.data[key] = value
        self.ttls[key] = ex

    def pipeline(self, transaction=True):
        outer = self

        class _Pipe:
            def __init__(self):
                self.ops = []

            def get(self, key):
                self.ops.append(("get", key))

            def delete(self, key):
                self.ops.append(("delete", key))

            def execute(self):
                if outer.fail:
                    raise ConnectionError("down")
                out = []
                for op, key in self.ops:
                    out.append(outer.data.get(key) if op == "get" else int(outer.data.pop(key, None) is not None))
                return out

        return _Pipe()


# ----------------------------------------------------------------------------------------------- headers


async def test_security_headers_on_a_normal_response(client):
    r = await client.get("/livez")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "camera=()" in r.headers["permissions-policy"]


async def test_security_headers_on_404_401_and_413(client):
    for response in (
        await client.get("/no-such-route"),
        await client.get("/api/state"),  # no credentials
        await client.post("/auth/login", content=b"x", headers={"content-length": str(50 * 1024 * 1024)}),
    ):
        assert response.status_code in (401, 403, 404, 413), response.status_code
        for name in HEADER_NAMES:
            assert name in response.headers, (response.status_code, name)
    assert (await client.post("/auth/login", content=b"x", headers={"content-length": "99999999"})).status_code == 413


async def test_headers_are_on_a_500_from_the_error_boundary(client, monkeypatch):
    import api.routes.health_routes as health

    async def boom(*_a, **_k):
        raise RuntimeError("secret-internal-detail /srv/app.py")

    monkeypatch.setattr(health, "_redis_state", boom)
    r = await client.get("/readyz")
    assert r.status_code == 500
    assert "secret-internal-detail" not in r.text and "/srv/app.py" not in r.text and "Traceback" not in r.text
    for name in HEADER_NAMES:
        assert name in r.headers


async def test_hsts_only_over_https(make_client, monkeypatch):
    async with make_client() as plain:
        assert "strict-transport-security" not in (await plain.get("/livez")).headers
    async with make_client(base_url="https://test") as secure:
        value = (await secure.get("/livez")).headers["strict-transport-security"]
    assert value.startswith("max-age=") and "includeSubDomains" in value


async def test_forwarded_proto_counts_only_when_proxy_headers_are_trusted(make_client, monkeypatch):
    forwarded = {"x-forwarded-proto": "https"}
    async with make_client() as c:
        assert "strict-transport-security" not in (await c.get("/livez", headers=forwarded)).headers  # spoofable
        monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
        assert "strict-transport-security" in (await c.get("/livez", headers=forwarded)).headers
        assert "strict-transport-security" not in (await c.get("/livez", headers={"x-forwarded-proto": "http"})).headers


# ----------------------------------------------------------------------------------------------- netlify.toml


def test_netlify_headers_are_configured():
    data = tomllib.loads((ROOT / "netlify.toml").read_text(encoding="utf-8"))
    blocks = [h for h in data["headers"] if h["for"] == "/*"]
    assert blocks, "no [[headers]] for /*"
    values = blocks[0]["values"]
    csp = {
        part.strip().split(" ", 1)[0]: part.strip()
        for part in values["Content-Security-Policy"].split(";")
        if part.strip()
    }
    assert csp["default-src"] == "default-src 'self'"
    assert csp["frame-ancestors"] == "frame-ancestors 'none'"
    assert csp["object-src"] == "object-src 'none'"
    connect = csp["connect-src"].split()[1:]
    assert connect[0] == "'self'"
    assert all(src.startswith(("https://", "wss://")) for src in connect[1:]), connect  # no wildcards, no plain http
    assert "*" not in values["Content-Security-Policy"].replace("*/", "")
    assert "script-src 'self'" in values["Content-Security-Policy"]
    assert "'unsafe-eval'" not in values["Content-Security-Policy"]
    assert values["X-Content-Type-Options"] == "nosniff"
    assert values["Referrer-Policy"] == "no-referrer"
    assert values["X-Frame-Options"] == "DENY"
    assert values["Strict-Transport-Security"].startswith("max-age=")
    assert "Permissions-Policy" in values
    assert data["redirects"], "the SPA fallback redirect must survive"


def test_netlify_connect_src_matches_the_documented_api_origin():
    docs = (ROOT / "DEPLOYMENT.md").read_text(encoding="utf-8")
    toml = (ROOT / "netlify.toml").read_text(encoding="utf-8")
    host = "function-bun-production-6ce5.up.railway.app"
    assert host in docs and f"https://{host}" in toml and f"wss://{host}" in toml


# ----------------------------------------------------------------------------------------------- ticket store


def test_ticket_is_single_use_and_stores_only_a_hash():
    ticket, ttl = ws_tickets.issue_ticket("7", time.time() + 600)
    assert ttl == 30 and len(ticket) >= 40
    assert all(ticket not in key and ticket not in value for key, (_exp, value) in ws_tickets._memory.items())
    first = ws_tickets.redeem_ticket(ticket)
    assert first is not None and first["sub"] == "7"
    assert ws_tickets.redeem_ticket(ticket) is None


def test_unknown_empty_and_oversized_tickets_are_rejected():
    assert ws_tickets.redeem_ticket("nope") is None
    assert ws_tickets.redeem_ticket("") is None
    assert ws_tickets.redeem_ticket("x" * 1000) is None


def test_ticket_expires_after_its_ttl(monkeypatch):
    monkeypatch.setenv("WS_TICKET_TTL_SECONDS", "5")
    ticket, ttl = ws_tickets.issue_ticket("1", time.time() + 600)
    assert ttl == 5
    real = time.time
    monkeypatch.setattr(ws_tickets.time, "time", lambda: real() + 6)
    assert ws_tickets.redeem_ticket(ticket) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 30), ("", 30), ("10", 10), ("0", 30), ("-3", 30), ("abc", 30), ("99999", 300)],
)
def test_ttl_configuration(monkeypatch, raw, expected):
    if raw is not None:
        monkeypatch.setenv("WS_TICKET_TTL_SECONDS", raw)
    assert ws_tickets.ticket_ttl_seconds() == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, True), ("", True), ("true", True), ("false", False), ("0", False), ("off", False), ("banana", True)],
)
def test_query_token_flag_defaults_to_true(monkeypatch, raw, expected):
    if raw is not None:
        monkeypatch.setenv("WS_ALLOW_QUERY_TOKEN", raw)
    assert ws_tickets.query_token_allowed() is expected


def test_redis_store_keys_by_hash_sets_ttl_and_is_single_use():
    fake = FakeRedis()
    ws_tickets.set_redis_factory(lambda: fake)
    ticket, _ = ws_tickets.issue_ticket("3", time.time() + 100)
    (key,) = fake.data
    assert key.startswith("ws_ticket:") and ticket not in key and ticket not in fake.data[key]
    assert fake.ttls[key] == 30
    assert ws_tickets.redeem_ticket(ticket)["sub"] == "3"
    assert fake.data == {}
    assert ws_tickets.redeem_ticket(ticket) is None


def test_production_refuses_the_memory_fallback(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(ws_tickets.TicketStoreUnavailable):
        ws_tickets.issue_ticket("1", time.time() + 100)
    assert ws_tickets._memory == {}


def test_production_with_redis_down_is_unavailable_not_silently_in_memory(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    fake = FakeRedis()
    fake.fail = True
    ws_tickets.set_redis_factory(lambda: fake)
    with pytest.raises(ws_tickets.TicketStoreUnavailable) as info:
        ws_tickets.issue_ticket("1", time.time() + 100)
    assert "redis://" not in str(info.value) and "pw" not in str(info.value)
    assert ws_tickets._memory == {}


def test_development_falls_back_to_memory_when_redis_is_down():
    fake = FakeRedis()
    fake.fail = True
    ws_tickets.set_redis_factory(lambda: fake)
    ticket, _ = ws_tickets.issue_ticket("9", time.time() + 100)
    assert ws_tickets.redeem_ticket(ticket)["sub"] == "9"


def test_startup_rule_requires_redis_only_when_query_tokens_are_off(monkeypatch):
    from api import startup_checks as sc

    monkeypatch.setenv("ENVIRONMENT", "production")
    assert "R13-ws-ticket-store" not in {r.id for r in sc.find_violations()}  # default: ?token= allowed
    monkeypatch.setenv("WS_ALLOW_QUERY_TOKEN", "false")
    assert "R13-ws-ticket-store" in {r.id for r in sc.find_violations()}
    monkeypatch.setenv("REDIS_URL", "redis://cache.internal:6379/0")
    assert "R13-ws-ticket-store" not in {r.id for r in sc.find_violations()}
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("REDIS_URL")
    assert "R13-ws-ticket-store" not in {r.id for r in sc.find_violations()}  # production-only rule


# ----------------------------------------------------------------------------------------------- ticket endpoint


async def test_ticket_endpoint_requires_a_valid_access_token(client):
    assert (await client.post("/auth/ws-ticket")).status_code in (401, 403)
    r = await client.post("/auth/ws-ticket", headers={"Authorization": "Bearer not.a.token"})
    assert r.status_code == 401


async def test_ticket_endpoint_issues_an_opaque_single_use_ticket(client, session_maker):
    user = await _user(session_maker)
    r = await client.post("/auth/ws-ticket", headers=_bearer(user))
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"ticket", "expires_in"} and body["expires_in"] == 30
    assert r.headers["cache-control"] == "no-store"
    assert body["ticket"].count(".") == 0  # not a JWT
    redeemed = ws_tickets.redeem_ticket(body["ticket"])
    assert redeemed is not None and redeemed["sub"] == str(user.id)
    assert redeemed["exp"] > time.time()  # the access token's own expiry travels with the ticket
    assert ws_tickets.redeem_ticket(body["ticket"]) is None


async def test_ticket_endpoint_is_503_in_production_without_redis_and_leaks_nothing(client, session_maker, monkeypatch):
    user = await _user(session_maker)
    monkeypatch.setenv("ENVIRONMENT", "production")
    r = await client.post("/auth/ws-ticket", headers=_bearer(user))
    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["type"].endswith("ws_ticket_unavailable")
    for needle in ("Traceback", "redis", "Redis", ".py", "/home"):
        assert needle not in r.text


async def test_ticket_endpoint_works_in_production_with_redis(client, session_maker, monkeypatch):
    user = await _user(session_maker)
    monkeypatch.setenv("ENVIRONMENT", "production")
    fake = FakeRedis()
    ws_tickets.set_redis_factory(lambda: fake)
    r = await client.post("/auth/ws-ticket", headers=_bearer(user))
    assert r.status_code == 200 and len(fake.data) == 1


async def test_ticket_endpoint_is_rate_limited(make_client, session_maker):
    user = await _user(session_maker)
    limiter.enabled = True
    limiter.reset()
    async with make_client() as c:
        codes = [(await c.post("/auth/ws-ticket", headers=_bearer(user))).status_code for _ in range(32)]
    assert codes[:30] == [200] * 30 and 429 in codes[30:]


# ----------------------------------------------------------------------------------------------- websocket


def _jwt(user_id=1, exp_in=900):
    from jose import jwt

    claims = {"sub": str(user_id), "role": "viewer", "exp": int(time.time()) + exp_in}
    return jwt.encode(claims, auth_module.SECRET_KEY, algorithm=auth_module.ALGORITHM)


def _close_code(url: str) -> int:
    with pytest.raises(WebSocketDisconnect) as info:
        with TestClient(app).websocket_connect(url) as ws:
            ws.receive_text()
    return info.value.code


@pytest.fixture
def clean_manager():
    def _reset():
        manager._connections.clear()
        manager._owners.clear()
        manager._per_user.clear()

    _reset()
    yield
    _reset()


def _wait(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_ws_accepts_a_valid_ticket_once(clean_manager):
    ticket, _ = ws_tickets.issue_ticket("5", time.time() + 600)
    client = TestClient(app)
    with client.websocket_connect(f"/ws/live?ticket={ticket}"):
        assert _wait(manager.has_connections)
    assert _wait(lambda: not manager.has_connections())
    assert _close_code(f"/ws/live?ticket={ticket}") == 4001  # single use


def test_ws_rejects_unknown_ticket_with_4001(clean_manager):
    assert _close_code("/ws/live?ticket=does-not-exist") == 4001


def test_ws_ticket_whose_session_already_ended_closes_with_4002(clean_manager):
    ticket, _ = ws_tickets.issue_ticket("5", time.time() - 1)
    assert _close_code(f"/ws/live?ticket={ticket}") == 4002


def test_ws_invalid_ticket_is_never_retried_as_a_token(clean_manager):
    assert _close_code(f"/ws/live?ticket=bad&token={_jwt()}") == 4001


def test_ws_token_flow_still_works_by_default(clean_manager):
    client = TestClient(app)
    with client.websocket_connect(f"/ws/live?token={_jwt()}"):
        assert _wait(manager.has_connections)


def test_ws_token_flow_is_closed_when_the_flag_is_off_but_tickets_still_work(clean_manager, monkeypatch):
    monkeypatch.setenv("WS_ALLOW_QUERY_TOKEN", "false")
    assert _close_code(f"/ws/live?token={_jwt()}") == 4001
    ticket, _ = ws_tickets.issue_ticket("5", time.time() + 600)
    with TestClient(app).websocket_connect(f"/ws/live?ticket={ticket}"):
        assert _wait(manager.has_connections)


def test_ws_without_any_credential_is_rejected(clean_manager):
    assert _close_code("/ws/live") == 4001


# ----------------------------------------------------------------------------------------------- redaction


def test_redact_token_covers_tickets_and_tokens():
    assert ws_routes.redact_token("/ws/live?ticket=abc_DEF-1") == "/ws/live?ticket=[REDACTED]"
    assert ws_routes.redact_token("/ws/live?a=1&TICKET=abc&b=2") == "/ws/live?a=1&TICKET=[REDACTED]&b=2"
    assert ws_routes.redact_token("/ws/live?token=eyJ.a.b") == "/ws/live?token=[REDACTED]"
    assert (
        ws_routes.redact_token("x?access_token=abc&refresh_token=def")
        == "x?access_token=[REDACTED]&refresh_token=[REDACTED]"
    )
    assert ws_routes.redact_token("nothing to see") == "nothing to see"


def test_server_loggers_never_print_a_ticket_or_token():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("uvicorn.access")
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.INFO)
    try:
        logger.info('%s - "%s %s HTTP/%s" %d', "1.2.3.4:5", "GET", "/ws/live?ticket=TICKETVALUE123", "1.1", 101)
        logger.info('%s - "%s %s HTTP/%s" %d', "1.2.3.4:5", "GET", "/ws/live?token=JWTVALUE456&x=1", "1.1", 101)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
    out = stream.getvalue()
    assert "TICKETVALUE123" not in out and "JWTVALUE456" not in out
    assert out.count("[REDACTED]") == 2


async def test_credentials_in_the_url_never_reach_error_bodies_or_metric_labels(client):
    secret = "SUPERSECRETVALUE987"
    for path in (
        f"/api/state?ticket={secret}&token={secret}",
        f"/no-such-route?ticket={secret}",
        f"/auth/ws-ticket?ticket={secret}",
    ):
        r = await client.get(path)
        assert secret not in r.text, path
        assert secret not in json.dumps(dict(r.headers)), path
    metrics_text = render_metrics()[0].decode()
    assert secret not in metrics_text


async def test_ticket_and_token_are_not_in_the_ticket_endpoints_logs(client, session_maker, caplog):
    user = await _user(session_maker)
    headers = _bearer(user)
    with caplog.at_level(logging.DEBUG):
        r = await client.post("/auth/ws-ticket", headers=headers)
    ticket = r.json()["ticket"]
    assert ticket not in caplog.text
    assert headers["Authorization"].split()[1] not in caplog.text


# ----------------------------------------------------------------------------------------------- login lockout


async def _login(c, username, password):
    return await c.post("/auth/login", json={"username": username, "password": password})


@pytest.fixture
def clock(monkeypatch):
    # The lockout is switched on explicitly so these tests never depend on slowapi's separate 10/minute login limit
    # (other test modules reload api.auth, which registers that limit twice on the shared limiter).
    monkeypatch.setenv("LOGIN_LOCKOUT_ENABLED", "true")
    state = {"t": 1000.0}
    monkeypatch.setattr(login_lockout, "now", lambda: state["t"])
    return state


async def test_lockout_after_threshold_failures_with_retry_after(make_client, session_maker, clock):
    await _user(session_maker)
    async with make_client() as c:
        for i in range(5):
            r = await _login(c, "alice", "wrong-password")
            assert r.status_code == 401, (i, r.text)
        locked = await _login(c, "alice", "correct-horse-1")  # even the right password is refused while locked
    assert locked.status_code == 429
    assert int(locked.headers["retry-after"]) == 30
    body = locked.json()
    assert body["type"].endswith("login_locked") and "alice" not in locked.text
    assert "x-request-id" in locked.headers and "x-frame-options" in locked.headers


async def test_lock_expires_and_backoff_doubles(make_client, session_maker, clock):
    await _user(session_maker)
    async with make_client() as c:
        for _ in range(5):
            await _login(c, "alice", "bad")
        assert (await _login(c, "alice", "bad")).status_code == 429
        clock["t"] += 31
        assert (await _login(c, "alice", "bad")).status_code == 401  # 6th failure -> lock doubles
        locked = await _login(c, "alice", "bad")
        assert locked.status_code == 429 and int(locked.headers["retry-after"]) == 60
        clock["t"] += 61
        assert (await _login(c, "alice", "correct-horse-1")).status_code == 200


async def test_lockout_is_per_ip_and_username_and_unknown_users_lock_too(
    make_client, session_maker, clock, monkeypatch
):
    monkeypatch.setenv("LOGIN_LOCKOUT_THRESHOLD", "3")  # keeps this test under the separate 10/minute per-IP limit
    await _user(session_maker)
    await _user(session_maker, username="bob")
    async with make_client("10.1.1.1") as attacker, make_client("10.2.2.2") as other:
        for _ in range(3):
            await _login(attacker, "alice", "bad")
            await _login(attacker, "no-such-user", "bad")
        assert (await _login(attacker, "alice", "bad")).status_code == 429
        assert (await _login(attacker, "no-such-user", "bad")).status_code == 429  # same answer: nothing leaked
        assert (await _login(attacker, "bob", "correct-horse-1")).status_code == 200  # different username
        assert (await _login(other, "alice", "correct-horse-1")).status_code == 200  # the real owner elsewhere


async def test_success_resets_the_failure_count(make_client, session_maker, clock):
    await _user(session_maker)
    async with make_client() as c:
        for _ in range(4):
            await _login(c, "alice", "bad")
        assert (await _login(c, "alice", "correct-horse-1")).status_code == 200
        for _ in range(4):
            assert (await _login(c, "alice", "bad")).status_code == 401
        assert (await _login(c, "alice", "correct-horse-1")).status_code == 200


async def test_failures_are_forgotten_after_the_reset_window(make_client, session_maker, clock):
    await _user(session_maker)
    async with make_client() as c:
        for _ in range(4):
            await _login(c, "alice", "bad")
        clock["t"] += 901
        assert (await _login(c, "alice", "bad")).status_code == 401  # counted as failure 1, not 5
        assert (await _login(c, "alice", "bad")).status_code == 401


async def test_lockout_follows_the_limiter_switch_by_default_and_the_flag_overrides(
    make_client, session_maker, clock, monkeypatch
):
    await _user(session_maker)
    monkeypatch.setenv("LOGIN_LOCKOUT_THRESHOLD", "1")
    monkeypatch.delenv("LOGIN_LOCKOUT_ENABLED")  # auto: the fixture left the shared limiter disabled
    async with make_client("10.3.3.3") as c:
        for _ in range(3):
            assert (await _login(c, "alice", "bad")).status_code == 401  # auto + limiter off: never locked
    monkeypatch.setenv("LOGIN_LOCKOUT_ENABLED", "false")
    async with make_client("10.4.4.4") as c:
        for _ in range(3):
            assert (await _login(c, "alice", "bad")).status_code == 401  # explicitly off
    monkeypatch.setenv("LOGIN_LOCKOUT_ENABLED", "true")
    async with make_client("10.5.5.5") as c:
        assert (await _login(c, "alice", "bad")).status_code == 401
        assert (await _login(c, "alice", "bad")).status_code == 429  # explicitly on, limiter off


def test_lockout_mode_parsing(monkeypatch):
    for raw, expected in (
        (None, "auto"),
        ("", "auto"),
        ("auto", "auto"),
        ("true", "on"),
        ("1", "on"),
        ("false", "off"),
        ("off", "off"),
    ):
        if raw is None:
            monkeypatch.delenv("LOGIN_LOCKOUT_ENABLED", raising=False)
        else:
            monkeypatch.setenv("LOGIN_LOCKOUT_ENABLED", raw)
        assert login_lockout.mode() == expected
    monkeypatch.delenv("LOGIN_LOCKOUT_ENABLED", raising=False)
    assert login_lockout.active(True) and not login_lockout.active(False)


async def test_malformed_or_oversized_login_bodies_pass_through_unguarded(make_client, session_maker):
    async with make_client() as c:
        assert (
            await c.post("/auth/login", content=b"{not json", headers={"content-type": "application/json"})
        ).status_code == 422
        assert (await c.post("/auth/login", json={"password": "x"})).status_code == 422
        big = {"username": "a" * 6000, "password": "x"}
        assert (await c.post("/auth/login", json=big)).status_code == 401


def test_lockout_keys_do_not_contain_the_username():
    key = login_lockout.make_key("1.2.3.4", "Alice@Example.com")
    assert "alice" not in key.lower() and len(key) == 64
    assert key == login_lockout.make_key("1.2.3.4", " alice@example.com ")
    assert key != login_lockout.make_key("1.2.3.5", "alice@example.com")


# ----------------------------------------------------------------------------------------------- /metrics, probes


async def test_metrics_is_closed_in_production_without_a_token(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    for headers in ({}, {"Authorization": "Bearer anything"}, {"Authorization": "Bearer "}):
        r = await client.get("/metrics", headers=headers)
        assert r.status_code == 401
        assert "http_requests_total" not in r.text


class _BrokenSession:
    async def execute(self, *_a, **_k):
        raise RuntimeError(
            'connection to server at "10.0.0.5", port 5432 failed: password authentication failed for user "twin" /var/lib/pg'
        )


async def test_probes_leak_nothing_when_the_database_is_down(make_client):
    async def broken_db():
        yield _BrokenSession()

    app.dependency_overrides[get_db] = broken_db
    async with make_client() as c:
        for path in ("/healthz", "/readyz", "/livez"):
            r = await c.get(path)
            text = r.text
            for needle in (
                "10.0.0.5",
                "5432",
                "password",
                '"twin"',
                "/var/lib",
                "Traceback",
                'File "',
                "sqlalchemy",
                "postgres",
                "://",
            ):
                assert needle not in text, (path, needle)
        assert (await c.get("/healthz")).status_code == 503
        assert (await c.get("/readyz")).status_code == 503
        assert (await c.get("/livez")).status_code == 200


async def test_readyz_body_exposes_only_statuses(client):
    r = await client.get("/readyz")
    body = r.json()
    assert set(body) == {
        "status",
        "checks",
        "degraded",
        "components",
        "broadcast_heartbeat_age_s",
        "broadcast_restarts",
        "timestamp",
    }
    flat = json.dumps(body)
    for needle in ("Traceback", "://", "/home", ".py", "password", "secret"):
        assert needle not in flat


async def test_healthz_body_is_minimal(client):
    body = (await client.get("/healthz")).json()
    assert set(body) == {"status", "database", "timestamp"}


# ----------------------------------------------------------------------------------------------- plugin wiring


def test_task6_plugins_are_loaded_in_the_real_app():
    results = {r.name: r.status for r in app.state.plugin_results}
    for name in ("security", "login_lockout", "ws_tickets"):
        assert results.get(name) == "loaded", results
