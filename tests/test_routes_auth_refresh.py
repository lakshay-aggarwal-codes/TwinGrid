"""/auth/register, /auth/login, /auth/refresh, /auth/logout (real bcrypt, real DB rows)."""

import pytest
from sqlalchemy import select

from api.rate_limit import limiter
from models.db_models import AuditLog, RefreshToken

PASSWORD = "correct-horse-battery"


async def _register(client, username, role="viewer", admin_key=None):
    headers = {"X-Admin-Key": admin_key} if admin_key else {}
    return await client.post(
        "/auth/register", json={"username": username, "password": PASSWORD, "role": role}, headers=headers
    )


async def _login(client, username):
    return await client.post("/auth/login", json={"username": username, "password": PASSWORD})


# ----------------------------------------------------------------------------- register
async def test_register_viewer_ok_and_password_not_returned(client):
    r = await _register(client, "alice")
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "alice" and body["role"] == "viewer"
    assert "password" not in body and "hashed_password" not in body


async def test_register_duplicate_username_400(client):
    await _register(client, "alice")
    assert (await _register(client, "alice")).status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "x", "password": "short"},  # password < 8
        {"username": "", "password": PASSWORD},  # empty username
        {"username": "x", "password": PASSWORD, "role": "admin"},  # role not allowed
    ],
)
async def test_register_validation(client, payload):
    assert (await client.post("/auth/register", json=payload)).status_code == 422


async def test_register_operator_without_key_is_403(client, monkeypatch):
    monkeypatch.setenv("OPERATOR_REGISTRATION_KEY", "secret-key")
    assert (await _register(client, "op", "operator")).status_code == 403
    assert (await _register(client, "op", "operator", admin_key="wrong")).status_code == 403


async def test_register_operator_disabled_when_key_unset(client, monkeypatch):
    monkeypatch.delenv("OPERATOR_REGISTRATION_KEY", raising=False)
    monkeypatch.delenv("OPERATOR_REGISTRATION_KEY_FILE", raising=False)
    assert (await _register(client, "op", "operator", admin_key="anything")).status_code == 403


async def test_register_operator_with_key_ok_and_audited(client, monkeypatch, session_maker):
    monkeypatch.setenv("OPERATOR_REGISTRATION_KEY", "secret-key")
    r = await _register(client, "op", "operator", admin_key="secret-key")
    assert r.status_code == 200 and r.json()["role"] == "operator"
    async with session_maker() as s:
        logs = (await s.execute(select(AuditLog).where(AuditLog.action == "operator_registration"))).scalars().all()
    assert len(logs) == 1 and logs[0].username == "op"


# ----------------------------------------------------------------------------- login
async def test_login_success_returns_both_tokens(client):
    await _register(client, "alice")
    r = await _login(client, "alice")
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["role"] == "viewer"
    assert body["access_token"] and body["refresh_token"]


async def test_login_access_token_works_on_protected_route(client):
    await _register(client, "alice")
    token = (await _login(client, "alice")).json()["access_token"]
    r = await client.get("/api/health", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


async def test_login_wrong_password_and_unknown_user_look_identical(client):
    await _register(client, "alice")
    wrong_pw = await client.post("/auth/login", json={"username": "alice", "password": "nope-nope-nope"})
    no_user = await client.post("/auth/login", json={"username": "ghost", "password": PASSWORD})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()  # no user-enumeration leak


async def test_refresh_token_stored_only_as_hash(client, session_maker):
    await _register(client, "alice")
    plaintext = (await _login(client, "alice")).json()["refresh_token"]
    async with session_maker() as s:
        rows = (await s.execute(select(RefreshToken))).scalars().all()
    assert len(rows) == 1
    assert plaintext not in rows[0].token_hash and len(rows[0].token_hash) == 64


# ----------------------------------------------------------------------------- refresh / logout
async def test_refresh_rotates_and_old_token_is_dead(client):
    await _register(client, "alice")
    first = (await _login(client, "alice")).json()

    r = await client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200
    second = r.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert second["access_token"]

    replay = await client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert replay.status_code == 401

    again = await client.post("/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert again.status_code == 200


async def test_refresh_with_garbage_token_401(client):
    assert (await client.post("/auth/refresh", json={"refresh_token": "garbage"})).status_code == 401


async def test_refresh_expired_token_401(client, session_maker):
    from datetime import datetime, timedelta, timezone

    await _register(client, "alice")
    token = (await _login(client, "alice")).json()["refresh_token"]
    async with session_maker() as s:
        row = (await s.execute(select(RefreshToken))).scalar_one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        await s.commit()
    assert (await client.post("/auth/refresh", json={"refresh_token": token})).status_code == 401


async def test_logout_revokes_refresh_token_and_is_idempotent(client):
    await _register(client, "alice")
    token = (await _login(client, "alice")).json()["refresh_token"]

    assert (await client.post("/auth/logout", json={"refresh_token": token})).status_code == 204
    assert (await client.post("/auth/refresh", json={"refresh_token": token})).status_code == 401
    assert (await client.post("/auth/logout", json={"refresh_token": token})).status_code == 204
    assert (await client.post("/auth/logout", json={"refresh_token": "never-existed"})).status_code == 204


@pytest.mark.xfail(
    strict=True,
    reason="Stage 1: no reuse detection - replaying a revoked refresh token should revoke the whole token family",
)
async def test_refresh_reuse_revokes_whole_family(client):
    await _register(client, "alice")
    first = (await _login(client, "alice")).json()
    second = (await client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})).json()

    await client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})  # attacker replays old token
    r = await client.post("/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert r.status_code == 401


# ----------------------------------------------------------------------------- rate limits
async def test_login_is_rate_limited(client):
    limiter.enabled = True
    limiter.reset()
    try:
        codes = []
        for _ in range(12):
            r = await client.post("/auth/login", json={"username": "ghost", "password": "whatever1"})
            codes.append(r.status_code)
        assert 429 in codes
        assert codes[0] == 401  # limiter only kicks in after the quota (10/min)
    finally:
        limiter.reset()
        limiter.enabled = False
