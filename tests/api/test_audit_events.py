"""T15 HTTP-level audit tests -- one section per row of the roadmap 8.4 table.

Each event is asserted to be written exactly once with every minimum field (actor, action, target, UTC
created_at, outcome, request_id, client_ip, details without secrets). Atomic events are shown to roll back
with the action when the audit write fails; best-effort events are shown to survive the request's rollback
and to never break it. The EVENT x TEST matrix is in reports/postT9/T15_evidence.md.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select

from api.middleware.metrics import registry
from api.routes import optimization_routes
from api.services import audit_service, optimization_service
from models.db_models import (
    Alert,
    Asset,
    AssetPose,
    AuditLog,
    Facility,
    OptimizationResult,
    RefreshToken,
    User,
)

PASSWORD = "a-long-enough-password"
ADMIN_KEY = "audit-test-admin-key"
CLIENT_IP = "127.0.0.1"  # httpx ASGITransport's default peer
SUMMARY = {
    "mean_pue": 1.3,
    "mean_wue": 0.5,
    "mean_cooling_power_kw": 80.0,
    "total_water_consumed_L": 1200.0,
    "total_reward": -50.0,
    "safety_violations": 0,
}


# ----------------------------------------------------------------------------- helpers
async def audit_rows(session_maker, action=None):
    async with session_maker() as s:
        stmt = select(AuditLog).order_by(AuditLog.id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        return (await s.execute(stmt)).scalars().all()


def assert_complete(row, *, action, outcome="success", request_id, target_type, actor=None):
    """Every minimum field of roadmap 8.4 is present on the row."""
    assert row.action == action
    assert row.outcome == outcome
    assert row.request_id == request_id
    assert row.client_ip == CLIENT_IP
    assert row.target_type == target_type and row.target_id
    assert row.created_at is not None
    if actor is not None:
        assert (row.user_id, row.username) == actor
    assert "password" not in json.dumps(row.details or {}).lower()


def rid(name: str) -> dict:
    return {"X-Request-ID": f"rid-{name}"}


def failures() -> float:
    return registry.get_sample_value("audit_write_failures_total") or 0.0


async def register(client, username="alice", role="viewer", admin_key=None, headers=None):
    h = dict(headers or {})
    if admin_key:
        h["X-Admin-Key"] = admin_key
    return await client.post(
        "/auth/register", json={"username": username, "password": PASSWORD, "role": role}, headers=h
    )


async def login(client, username="alice", password=PASSWORD, headers=None):
    return await client.post("/auth/login", json={"username": username, "password": password}, headers=headers)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("ALLOW_PUBLIC_REGISTRATION", raising=False)
    monkeypatch.delenv("OPERATOR_REGISTRATION_KEY_FILE", raising=False)
    monkeypatch.setenv("OPERATOR_REGISTRATION_KEY", ADMIN_KEY)


@pytest.fixture
def fake_optimizer(monkeypatch):
    async def fake_run(alpha, beta, gamma, water_stress, hours):
        return [{"pue": 1.3, "timestamp": datetime(2026, 1, 1), "cooling_mode": "hybrid"}], dict(SUMMARY)

    monkeypatch.setattr(optimization_service, "run_optimization", fake_run)


@pytest.fixture
def break_atomic_audit(monkeypatch):
    async def boom(*args, **kwargs):
        raise audit_service.AuditWriteError("audit store unavailable")

    monkeypatch.setattr(audit_service, "log_action", boom)


@pytest.fixture
def webhook_file(tmp_path, monkeypatch):
    import src.webhook_registry as webhook_registry
    from api.services import webhook_security

    monkeypatch.setattr(webhook_registry, "REGISTRY_PATH", tmp_path / "webhooks.json")
    monkeypatch.setattr(webhook_security, "_resolve_host", lambda host, port: ["93.184.216.34"])
    monkeypatch.delenv("WEBHOOK_ALLOW_HTTP", raising=False)
    return webhook_registry.REGISTRY_PATH


# ============================================================================= operator registration (atomic)
async def test_operator_registration_event(client, session_maker):
    r = await register(client, "op-new", "operator", admin_key=ADMIN_KEY, headers=rid("opreg"))
    assert r.status_code == 200
    (row,) = await audit_rows(session_maker, "operator_registration")
    assert_complete(
        row,
        action="operator_registration",
        request_id="rid-opreg",
        target_type="user",
        actor=(r.json()["id"], "op-new"),
    )
    assert row.target_id == str(r.json()["id"])
    assert ADMIN_KEY not in json.dumps(row.details)  # the key is never stored
    assert row.details["admin_key_supplied"] is True


async def test_viewer_registration_is_not_an_audited_event(client, session_maker):
    assert (await register(client, "plain")).status_code == 200
    assert await audit_rows(session_maker) == []


async def test_operator_registration_rolls_back_when_audit_write_fails(
    client, session_maker, break_atomic_audit, count_rows
):
    r = await register(client, "op-lost", "operator", admin_key=ADMIN_KEY)
    assert r.status_code == 500
    assert await count_rows(User, User.username == "op-lost") == 0  # the account was NOT created


# ============================================================================= login / logout / refresh (best-effort)
async def test_login_success_event(client, session_maker):
    reg = await register(client)
    r = await login(client, headers=rid("login-ok"))
    assert r.status_code == 200
    (row,) = await audit_rows(session_maker, "login_success")
    assert_complete(
        row,
        action="login_success",
        request_id="rid-login-ok",
        target_type="user",
        actor=(reg.json()["id"], "alice"),
    )


async def test_login_failure_event_known_account(client, session_maker):
    reg = await register(client)
    r = await login(client, password="wrong-password-123", headers=rid("login-bad"))
    assert r.status_code == 401
    (row,) = await audit_rows(session_maker, "login_failure")
    assert_complete(
        row,
        action="login_failure",
        outcome="denied",
        request_id="rid-login-bad",
        target_type="user",
        actor=(reg.json()["id"], "alice"),
    )
    assert "wrong-password-123" not in json.dumps(row.details)
    assert await audit_rows(session_maker, "login_success") == []


async def test_login_failure_unknown_account_stores_no_attempted_username(client, session_maker):
    r = await login(client, username="hunter2-pasted-as-username", headers=rid("login-unknown"))
    assert r.status_code == 401
    (row,) = await audit_rows(session_maker, "login_failure")
    assert row.user_id is None and row.username is None
    assert row.outcome == "denied" and row.request_id == "rid-login-unknown" and row.client_ip == CLIENT_IP
    assert "hunter2" not in json.dumps(row.details) and row.details["account_exists"] is False


async def test_refresh_reuse_detected_event(client, session_maker):
    reg = await register(client)
    first = (await login(client)).json()["refresh_token"]
    rotated = await client.post("/auth/refresh", json={"refresh_token": first})
    assert rotated.status_code == 200
    replay = await client.post("/auth/refresh", json={"refresh_token": first}, headers=rid("reuse"))
    assert replay.status_code == 401
    (row,) = await audit_rows(session_maker, "refresh_reuse_detected")
    assert_complete(
        row,
        action="refresh_reuse_detected",
        outcome="denied",
        request_id="rid-reuse",
        target_type="user",
        actor=(reg.json()["id"], "alice"),
    )
    assert first not in json.dumps(row.details)


async def test_invalid_refresh_token_is_not_a_reuse_event(client, session_maker):
    assert (await client.post("/auth/refresh", json={"refresh_token": "never-issued"})).status_code == 401
    assert await audit_rows(session_maker, "refresh_reuse_detected") == []


async def test_logout_event_once_and_only_when_a_token_was_revoked(client, session_maker):
    reg = await register(client)
    token = (await login(client)).json()["refresh_token"]
    r = await client.post("/auth/logout", json={"refresh_token": token}, headers=rid("logout"))
    assert r.status_code == 204
    again = await client.post("/auth/logout", json={"refresh_token": token})
    assert again.status_code == 204  # idempotent, unchanged
    (row,) = await audit_rows(session_maker, "logout")  # second call revoked nothing -> no second row
    assert_complete(
        row, action="logout", request_id="rid-logout", target_type="user", actor=(reg.json()["id"], "alice")
    )


async def test_best_effort_events_survive_the_requests_rollback(client, session_maker, count_rows):
    """login_failure is written by an independent session: the 401 does not erase it."""
    await login(client, username="nobody")
    assert await count_rows(AuditLog, AuditLog.action == "login_failure") == 1


async def test_best_effort_audit_failure_never_breaks_the_request(client, session_maker):
    await register(client)

    def broken_factory():
        raise RuntimeError("audit database unreachable")

    audit_service.set_session_factory(broken_factory)
    before = failures()
    ok = await login(client)
    bad = await login(client, password="nope-nope-nope")
    assert ok.status_code == 200 and bad.status_code == 401  # status codes unchanged
    assert failures() == before + 2


# ============================================================================= permission denied (best-effort)
async def test_permission_denied_event_for_viewer_on_operator_route(client, viewer_headers, session_maker):
    r = await client.post("/api/optimize", json={}, headers={**viewer_headers, **rid("denied")})
    assert r.status_code == 403
    (row,) = await audit_rows(session_maker, "permission_denied")
    assert_complete(
        row,
        action="permission_denied",
        outcome="denied",
        request_id="rid-denied",
        target_type="endpoint",
        actor=(row.user_id, "viewer1"),
    )
    assert row.target_id == "POST /api/optimize"
    assert row.details["required_role"] == "operator" and row.details["actual_role"] == "viewer"


async def test_permission_denied_event_for_closed_registration(client, session_maker, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    r = await register(client, headers=rid("reg-closed"))
    assert r.status_code == 403
    (row,) = await audit_rows(session_maker, "permission_denied")
    assert_complete(
        row, action="permission_denied", outcome="denied", request_id="rid-reg-closed", target_type="endpoint"
    )
    assert row.target_id == "POST /auth/register" and row.user_id is None


async def test_permission_denied_covers_other_operator_routes(client, viewer_headers, session_maker):
    assert (await client.post("/api/alerts/1/acknowledge", headers=viewer_headers)).status_code == 403
    (row,) = await audit_rows(session_maker, "permission_denied")
    assert row.target_id == "POST /api/alerts/1/acknowledge"


async def test_operator_access_writes_no_denied_event(client, operator_headers, fake_optimizer, session_maker):
    assert (await client.post("/api/optimize", json={}, headers=operator_headers)).status_code == 200
    assert await audit_rows(session_maker, "permission_denied") == []


async def test_permission_denied_audit_failure_keeps_the_403(client, viewer_headers):
    def broken_factory():
        raise RuntimeError("audit database unreachable")

    audit_service.set_session_factory(broken_factory)
    before = failures()
    assert (await client.post("/api/optimize", json={}, headers=viewer_headers)).status_code == 403
    assert failures() == before + 1


# ============================================================================= optimize / train_async (atomic)
async def test_optimize_triggered_event(client, operator_headers, fake_optimizer, session_maker):
    r = await client.post("/api/optimize", json={"hours": 12}, headers={**operator_headers, **rid("opt")})
    assert r.status_code == 200
    (row,) = await audit_rows(session_maker, "optimize_triggered")
    async with session_maker() as s:
        saved = (await s.execute(select(OptimizationResult))).scalars().one()
    assert_complete(
        row,
        action="optimize_triggered",
        request_id="rid-opt",
        target_type="optimization_result",
        actor=(row.user_id, "operator1"),
    )
    assert row.target_id == str(saved.id) and row.details["hours"] == 12


async def test_optimize_rolls_back_when_audit_write_fails(
    client, operator_headers, fake_optimizer, break_atomic_audit, count_rows
):
    r = await client.post("/api/optimize", json={}, headers=operator_headers)
    assert r.status_code == 500
    assert await count_rows(OptimizationResult) == 0  # the persisted result was rolled back


async def test_train_async_enqueued_event(client, operator_headers, session_maker, monkeypatch):
    seen = {}

    def fake_enqueue(path, *args, **kwargs):
        seen.update(path=path, args=args, kwargs=kwargs)
        return kwargs["job_id"]

    monkeypatch.setattr(optimization_routes, "enqueue", fake_enqueue)
    r = await client.post("/api/optimize/train_async", json={"alpha": 0.6}, headers={**operator_headers, **rid("ta")})
    assert r.status_code == 200 and r.json() == {"job_id": seen["kwargs"]["job_id"]}
    (row,) = await audit_rows(session_maker, "train_async_enqueued")
    assert_complete(
        row,
        action="train_async_enqueued",
        request_id="rid-ta",
        target_type="training_job",
        actor=(row.user_id, "operator1"),
    )
    assert row.target_id == seen["kwargs"]["job_id"] and row.details["alpha"] == 0.6


async def test_train_async_not_enqueued_when_audit_write_fails(
    client, operator_headers, break_atomic_audit, monkeypatch, session_maker
):
    calls = []
    monkeypatch.setattr(optimization_routes, "enqueue", lambda *a, **k: calls.append(1) or "job")
    r = await client.post("/api/optimize/train_async", json={}, headers=operator_headers)
    assert r.status_code == 500 and calls == []  # audit first: nothing was enqueued


async def test_train_async_audit_row_rolled_back_when_enqueue_fails(
    client, operator_headers, session_maker, monkeypatch
):
    def down(*args, **kwargs):
        raise RedisConnectionError("redis is down")

    monkeypatch.setattr(optimization_routes, "enqueue", down)
    assert (await client.post("/api/optimize/train_async", json={}, headers=operator_headers)).status_code == 503
    assert await audit_rows(session_maker, "train_async_enqueued") == []


# ============================================================================= webhooks (atomic)
async def test_webhook_registered_and_unregistered_events(client, operator_headers, webhook_file, session_maker):
    url = "https://hooks.example.com/services/T000/B000/SECRETTOKEN?sig=abc"
    r = await client.post("/api/webhooks", params={"url": url}, headers={**operator_headers, **rid("wh-reg")})
    assert r.status_code == 200
    (reg_row,) = await audit_rows(session_maker, "webhook_registered")
    assert_complete(
        reg_row,
        action="webhook_registered",
        request_id="rid-wh-reg",
        target_type="webhook",
        actor=(reg_row.user_id, "operator1"),
    )
    assert reg_row.target_id == audit_service.url_fingerprint(url)
    assert reg_row.details["host"] == "hooks.example.com"

    r = await client.delete("/api/webhooks", params={"url": url}, headers={**operator_headers, **rid("wh-del")})
    assert r.status_code == 200
    (del_row,) = await audit_rows(session_maker, "webhook_unregistered")
    assert_complete(
        del_row,
        action="webhook_unregistered",
        request_id="rid-wh-del",
        target_type="webhook",
        actor=(del_row.user_id, "operator1"),
    )
    for row in (reg_row, del_row):  # webhook URLs can embed secrets: only host + fingerprint are stored
        assert "SECRETTOKEN" not in json.dumps(row.details) and "sig=abc" not in json.dumps(row.details)


async def test_webhook_not_registered_when_audit_write_fails(
    client, operator_headers, webhook_file, break_atomic_audit
):
    r = await client.post("/api/webhooks", params={"url": "https://example.com/hook"}, headers=operator_headers)
    assert r.status_code == 500
    assert not webhook_file.exists()  # audit is written before the registry file is touched


async def test_webhook_audit_row_rolled_back_when_registry_refuses(
    client, operator_headers, webhook_file, session_maker, monkeypatch
):
    import src.webhook_registry as webhook_registry

    monkeypatch.setattr(webhook_registry, "MAX_SUBSCRIBERS", 0)
    r = await client.post("/api/webhooks", params={"url": "https://example.com/hook"}, headers=operator_headers)
    assert r.status_code == 409
    assert await audit_rows(session_maker, "webhook_registered") == []


# ============================================================================= alerts + facility writes (atomic, existing)
async def test_alert_acknowledged_event(client, operator_headers, session_maker):
    async with session_maker() as s:
        s.add(
            Alert(
                score=1.0,
                alert=True,
                type="thermal_spike",
                message="m",
                severity="WARNING",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
        await s.commit()
    r = await client.post("/api/alerts/1/acknowledge", headers={**operator_headers, **rid("ack")})
    assert r.status_code == 200
    (row,) = await audit_rows(session_maker, "alert_acknowledged")
    assert_complete(
        row,
        action="alert_acknowledged",
        request_id="rid-ack",
        target_type="alert",
        actor=(row.user_id, "operator1"),
    )
    assert row.target_id == "1"


async def test_alert_not_acknowledged_when_audit_write_fails(
    client, operator_headers, session_maker, break_atomic_audit
):
    async with session_maker() as s:
        s.add(
            Alert(
                score=1.0,
                alert=True,
                type="thermal_spike",
                message="m",
                severity="WARNING",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
        await s.commit()
    assert (await client.post("/api/alerts/1/acknowledge", headers=operator_headers)).status_code == 500
    async with session_maker() as s:
        assert (await s.get(Alert, 1)).acknowledged is False


@pytest.fixture
async def small_world(session_maker):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with session_maker() as s:
        f = Facility(name="F", frame_unit="m", frame_note="note")
        s.add(f)
        await s.flush()
        rack = Asset(facility_id=f.id, asset_type="rack", external_id="r1", name="r1")
        s.add(rack)
        await s.flush()
        s.add(AssetPose(asset_id=rack.id, x=1, y=1, z=0, rotation_deg=0, valid_from=t0))
        await s.commit()
        return {"rack": rack.id, "t0": t0}


async def test_facility_write_event_has_all_fields(client, operator_headers, small_world, session_maker):
    payload = {"x": 4, "y": 1, "z": 1, "valid_from": (small_world["t0"] + timedelta(days=2)).isoformat()}
    r = await client.post(
        f"/api/assets/{small_world['rack']}/move", json=payload, headers={**operator_headers, **rid("move")}
    )
    assert r.status_code == 201
    (row,) = await audit_rows(session_maker, "asset_move")
    assert_complete(
        row, action="asset_move", request_id="rid-move", target_type="asset", actor=(row.user_id, "operator1")
    )
    assert row.target_id == str(small_world["rack"])


# ============================================================================= not audited
async def test_read_only_gets_write_no_audit_rows(client, viewer_headers, session_maker):
    for path in ("/api/alerts", "/api/anomaly/status", "/api/assets", "/healthz"):
        await client.get(path, headers=viewer_headers)
    assert await audit_rows(session_maker) == []


async def test_failed_atomic_actions_leave_no_orphan_rows(client, session_maker, count_rows):
    assert (await client.post("/api/alerts/999/acknowledge")).status_code in (401, 403)
    assert await count_rows(AuditLog) == 0 and await count_rows(RefreshToken) == 0
