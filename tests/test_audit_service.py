"""T15 service-level tests for api/services/audit_service.py (roadmap 8.4).

In-memory SQLite, no HTTP. Covers: every minimum field is stored; outcome validation (service + DB CHECK);
secret scrubbing; trusted-proxy-aware client_ip; atomic writes share the caller's transaction; best-effort
writes use an independent session, never raise and count failures; model lifecycle helper.
"""

from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-suite-only")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from starlette.requests import Request  # noqa: E402

from api import config, rate_limit  # noqa: E402
from api.middleware.metrics import registry  # noqa: E402
from api.middleware.request_id import request_id_var  # noqa: E402
from api.services import audit_service  # noqa: E402
from models.db_models import AUDIT_OUTCOMES, AuditLog, Base, User  # noqa: E402


@pytest_asyncio.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _bind_factory(maker):
    audit_service.set_session_factory(maker)
    yield
    audit_service.set_session_factory(None)


def make_request(peer="203.0.113.9", headers=None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/x",
            "query_string": b"",
            "headers": raw,
            "client": (peer, 4321),
            "server": ("test", 80),
            "scheme": "http",
        }
    )


async def _user(maker, name="op1", role="operator") -> User:
    async with maker() as s:
        u = User(username=name, hashed_password="x", role=role)
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


async def _rows(maker, *where):
    async with maker() as s:
        stmt = select(AuditLog).order_by(AuditLog.id)
        for w in where:
            stmt = stmt.where(w)
        return (await s.execute(stmt)).scalars().all()


def _counter() -> float:
    return registry.get_sample_value("audit_write_failures_total") or 0.0


# ----------------------------------------------------------------------------- fields / contract
async def test_atomic_row_has_every_minimum_field(maker):
    user = await _user(maker)
    req = make_request(headers={"X-Request-ID": "req-123"})
    async with maker() as s:
        await audit_service.log_action(
            s,
            action="optimize_triggered",
            user=user,
            resource_type="optimization_result",
            resource_id=7,
            details={"alpha": 0.5},
            request=req,
        )
        await s.commit()
    (row,) = await _rows(maker)
    assert (row.user_id, row.username) == (user.id, "op1")  # actor id + username
    assert row.action == "optimize_triggered"
    assert (row.target_type, row.target_id) == ("optimization_result", "7")
    assert row.created_at is not None
    assert row.outcome == "success"
    assert row.request_id == "req-123"
    assert row.client_ip == "203.0.113.9"
    assert row.details == {"alpha": 0.5}


async def test_created_at_is_utc_aware_when_written(maker):
    async with maker() as s:
        entry = await audit_service.log_action(s, action="x")
        assert entry.created_at.tzinfo is not None and entry.created_at.utcoffset().total_seconds() == 0
        await s.commit()


async def test_request_id_prefers_middleware_context(maker):
    token = request_id_var.set("ctx-id-1")
    try:
        async with maker() as s:
            entry = await audit_service.log_action(s, action="x", request=make_request(headers={"X-Request-ID": "h"}))
            await s.commit()
    finally:
        request_id_var.reset(token)
    assert entry.request_id == "ctx-id-1"


@pytest.mark.parametrize("outcome", AUDIT_OUTCOMES)
async def test_valid_outcomes_are_stored(maker, outcome):
    async with maker() as s:
        await audit_service.log_action(s, action="x", outcome=outcome)
        await s.commit()
    assert (await _rows(maker))[0].outcome == outcome


async def test_invalid_outcome_rejected_by_service(maker):
    async with maker() as s:
        with pytest.raises(ValueError):
            await audit_service.log_action(s, action="x", outcome="maybe")


async def test_invalid_outcome_rejected_by_db_check(maker):
    async with maker() as s:
        s.add(AuditLog(action="x", outcome="maybe"))
        with pytest.raises(IntegrityError):
            await s.flush()


async def test_outcome_defaults_to_success_in_db(maker):
    """The server_default is what backfills legacy rows."""
    async with maker() as s:
        s.add(AuditLog(action="legacy-like"))
        await s.commit()
    assert (await _rows(maker))[0].outcome == "success"


# ----------------------------------------------------------------------------- details hygiene
def test_secret_looking_keys_are_redacted_recursively():
    cleaned = audit_service.sanitize_details(
        {"password": "p", "nested": {"refresh_token": "t", "X-Admin-Key": "k", "ok": 1}, "list": [{"secret": "s"}]}
    )
    assert cleaned["password"] == "[redacted]"
    assert cleaned["nested"] == {"refresh_token": "[redacted]", "X-Admin-Key": "[redacted]", "ok": 1}
    assert cleaned["list"] == [{"secret": "[redacted]"}]


def test_details_are_json_safe_and_bounded():
    cleaned = audit_service.sanitize_details({"obj": object(), "long": "x" * 5000})
    assert isinstance(cleaned["obj"], str)
    assert len(cleaned["long"]) < 600


def test_describe_url_never_contains_path_or_query():
    d = audit_service.describe_url("https://hooks.example.com/services/T000/B000/SECRETTOKEN?k=v")
    assert d["host"] == "hooks.example.com" and d["scheme"] == "https"
    assert "SECRETTOKEN" not in str(d) and "k=v" not in str(d)


# ----------------------------------------------------------------------------- client_ip
def test_client_ip_ignores_forwarded_for_unless_proxy_trusted(monkeypatch):
    monkeypatch.setattr(config, "trust_proxy_headers", lambda: False, raising=False)
    monkeypatch.setattr(config, "trusted_proxy_hops", lambda: 1, raising=False)
    req = make_request(peer="10.0.0.1", headers={"X-Forwarded-For": "198.51.100.7, 10.0.0.1"})
    assert audit_service.resolve_client_ip(req) == "10.0.0.1"


def test_client_ip_uses_nearest_trusted_hop_not_leftmost(monkeypatch):
    monkeypatch.setattr(config, "trust_proxy_headers", lambda: True, raising=False)
    monkeypatch.setattr(config, "trusted_proxy_hops", lambda: 1, raising=False)
    req = make_request(peer="10.0.0.1", headers={"X-Forwarded-For": "6.6.6.6, 198.51.100.7"})
    assert audit_service.resolve_client_ip(req) == "198.51.100.7"  # same answer as rate_limit.client_ip
    assert audit_service.resolve_client_ip(req) == rate_limit.client_ip(req)


def test_client_ip_falls_back_to_peer_if_proxy_rules_cannot_run(monkeypatch):
    def boom(_request):
        raise AttributeError("config helper missing")

    monkeypatch.setattr(rate_limit, "client_ip", boom)
    req = make_request(peer="192.0.2.5", headers={"X-Forwarded-For": "6.6.6.6"})
    assert audit_service.resolve_client_ip(req) == "192.0.2.5"


def test_client_ip_drops_unparsable_values(monkeypatch):
    monkeypatch.setattr(rate_limit, "client_ip", lambda _r: "not-an-ip")
    assert audit_service.resolve_client_ip(make_request()) is None
    assert audit_service.resolve_client_ip(None) is None


# ----------------------------------------------------------------------------- atomic semantics
async def test_atomic_row_rolls_back_with_the_action(maker):
    async with maker() as s:
        s.add(User(username="ghost", hashed_password="x", role="viewer"))
        await audit_service.log_action(s, action="operator_registration", resource_type="user")
        await s.rollback()  # the action fails after the audit row was flushed
    assert await _rows(maker) == []
    async with maker() as s:
        assert (await s.execute(select(User).where(User.username == "ghost"))).first() is None


async def test_atomic_failure_raises_audit_write_error(maker, monkeypatch):
    async with maker() as s:

        async def broken_flush(self, *a, **k):
            raise RuntimeError("db down")

        monkeypatch.setattr(AsyncSession, "flush", broken_flush)
        with pytest.raises(audit_service.AuditWriteError):
            await audit_service.log_action(s, action="optimize_triggered")


# ----------------------------------------------------------------------------- best effort
async def test_best_effort_uses_an_independent_committed_session(maker):
    async with maker() as request_session:
        request_session.add(User(username="pending", hashed_password="x", role="viewer"))
        row_id = await audit_service.log_action_best_effort(action="login_failure", outcome="denied")
        await request_session.rollback()  # the request's own work is discarded
    assert row_id is not None
    (row,) = await _rows(maker)
    assert (row.action, row.outcome) == ("login_failure", "denied")


async def test_best_effort_never_raises_and_counts_session_failures():
    def broken_factory():
        raise RuntimeError("cannot connect")

    audit_service.set_session_factory(broken_factory)
    before = _counter()
    assert await audit_service.log_action_best_effort(action="login_success") is None
    assert _counter() == before + 1


async def test_best_effort_never_raises_on_commit_failure(maker, monkeypatch):
    before = _counter()

    async def broken_commit(self):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(AsyncSession, "commit", broken_commit)
    assert await audit_service.log_action_best_effort(action="logout") is None
    assert _counter() == before + 1


async def test_best_effort_never_raises_on_bad_arguments():
    before = _counter()
    assert await audit_service.log_action_best_effort(action="x", outcome="nope") is None
    assert await audit_service.log_action_best_effort(action="") is None
    assert _counter() == before + 2


# ----------------------------------------------------------------------------- event table + model events
def test_event_table_matches_roadmap_modes():
    atomic = {k for k, v in audit_service.EVENT_MODES.items() if v == "atomic"}
    best = {k for k, v in audit_service.EVENT_MODES.items() if v == "best_effort"}
    assert best == {"login_success", "login_failure", "refresh_reuse_detected", "logout", "permission_denied"}
    assert {
        "operator_registration",
        "optimize_triggered",
        "train_async_enqueued",
        "webhook_registered",
        "webhook_unregistered",
        "alert_acknowledged",
        "asset_move",
        "asset_edge_create",
        "asset_edge_close",
        "model_promoted",
        "model_rejected",
        "model_quarantined",
    } == atomic


@pytest.mark.parametrize("action", audit_service.MODEL_EVENT_ACTIONS)
async def test_model_event_is_atomic_and_complete(maker, action):
    user = await _user(maker)
    async with maker() as s:
        await audit_service.log_model_event(
            s, action=action, model_name="anomaly", version="20260927T143232Z", user=user, details={"why": "gate"}
        )
        await s.commit()
    (row,) = await _rows(maker)
    assert (row.action, row.target_type, row.target_id) == (action, "model", "anomaly@20260927T143232Z")
    assert row.username == "op1" and row.outcome == "success" and row.details["why"] == "gate"


async def test_model_event_failure_propagates_so_the_cli_can_exit_nonzero(maker, monkeypatch):
    async with maker() as s:

        async def broken_flush(self, *a, **k):
            raise RuntimeError("db down")

        monkeypatch.setattr(AsyncSession, "flush", broken_flush)
        with pytest.raises(audit_service.AuditWriteError):
            await audit_service.log_model_event(s, action="model_promoted", model_name="m", version="1")


async def test_model_event_rejects_other_actions(maker):
    async with maker() as s:
        with pytest.raises(ValueError):
            await audit_service.log_model_event(s, action="asset_move", model_name="m", version="1")
