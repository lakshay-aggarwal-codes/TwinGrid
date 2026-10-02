"""T4a: ALLOW_PUBLIC_REGISTRATION, and viewer/operator separation on write routes."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from api.auth import public_registration_enabled
from models.db_models import Alert, AuditLog

PASSWORD = "a-long-enough-password"
ADMIN_KEY = "test-admin-key"


def _body(username="newuser", role="viewer"):
    return {"username": username, "password": PASSWORD, "role": role}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("ALLOW_PUBLIC_REGISTRATION", raising=False)
    monkeypatch.delenv("OPERATOR_REGISTRATION_KEY_FILE", raising=False)
    monkeypatch.setenv("OPERATOR_REGISTRATION_KEY", ADMIN_KEY)


# ----------------------------------------------------------------------------- registration flag
@pytest.mark.parametrize(
    "environment,flag,expected",
    [
        ("development", None, True),  # default: on in development
        ("production", None, False),  # default: off in production
        ("Production ", None, False),  # tolerant of case/whitespace
        ("production", "true", True),
        ("production", "1", True),
        ("development", "false", False),
        ("development", "0", False),
        ("development", "off", False),
        ("development", "maybe", False),  # unrecognised -> fail closed, even in development
        ("production", "", False),  # blank == unset
        ("development", "", True),
    ],
)
def test_public_registration_enabled_matrix(monkeypatch, environment, flag, expected):
    monkeypatch.setenv("ENVIRONMENT", environment)
    if flag is None:
        monkeypatch.delenv("ALLOW_PUBLIC_REGISTRATION", raising=False)
    else:
        monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", flag)
    assert public_registration_enabled() is expected


async def test_registration_open_by_default_in_development(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    r = await client.post("/auth/register", json=_body("dev_user"))
    assert r.status_code == 200 and r.json()["role"] == "viewer"


async def test_registration_closed_by_default_in_production(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    r = await client.post("/auth/register", json=_body("prod_user"))
    assert r.status_code == 403
    assert "disabled" in r.json()["detail"].lower()


async def test_flag_false_closes_registration_in_development(client, monkeypatch, count_rows):
    from models.db_models import User

    monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", "false")
    r = await client.post("/auth/register", json=_body("closed_user"))
    assert r.status_code == 403
    assert await count_rows(User) == 0  # nothing was created


async def test_flag_true_opens_registration_in_production(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", "true")
    assert (await client.post("/auth/register", json=_body("opened_user"))).status_code == 200


async def test_disabled_registration_still_allows_an_administrator_with_the_key(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    headers = {"X-Admin-Key": ADMIN_KEY}
    r = await client.post("/auth/register", json=_body("provisioned_viewer"), headers=headers)
    assert r.status_code == 200 and r.json()["role"] == "viewer"
    r = await client.post("/auth/register", json=_body("provisioned_op", "operator"), headers=headers)
    assert r.status_code == 200 and r.json()["role"] == "operator"


async def test_disabled_registration_rejects_a_wrong_key(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    r = await client.post("/auth/register", json=_body("x"), headers={"X-Admin-Key": "wrong"})
    assert r.status_code == 403


async def test_disabled_registration_with_no_server_key_configured_is_fully_closed(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("OPERATOR_REGISTRATION_KEY", raising=False)
    r = await client.post("/auth/register", json=_body("x"), headers={"X-Admin-Key": ""})
    assert r.status_code == 403
    r = await client.post("/auth/register", json=_body("x"), headers={"X-Admin-Key": ADMIN_KEY})
    assert r.status_code == 403


async def test_login_and_refresh_still_work_when_registration_is_disabled(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert (await client.post("/auth/register", json=_body("keeps_working"))).status_code == 200
    monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", "false")
    login = await client.post("/auth/login", json={"username": "keeps_working", "password": PASSWORD})
    assert login.status_code == 200
    refreshed = await client.post("/auth/refresh", json={"refresh_token": login.json()["refresh_token"]})
    assert refreshed.status_code == 200
    out = await client.post("/auth/logout", json={"refresh_token": refreshed.json()["refresh_token"]})
    assert out.status_code == 204


# ----------------------------------------------------------------------------- role separation
OPERATOR_ROUTES = [
    ("POST", "/api/webhooks?url=http://insecure.example/hook", None),
    ("DELETE", "/api/webhooks?url=http://insecure.example/hook", None),
    ("POST", "/api/alerts/1/acknowledge", None),
    ("POST", "/api/optimize", {}),
    ("POST", "/api/optimize/train_async", {}),
    ("GET", "/api/optimize/jobs/does-not-exist", None),
]


@pytest.mark.parametrize("method,path,body", OPERATOR_ROUTES)
async def test_viewer_gets_403_on_every_operator_route(client, viewer_headers, method, path, body):
    r = await client.request(method, path, headers=viewer_headers, json=body)
    assert r.status_code == 403, (method, path, r.text)


@pytest.mark.parametrize("method,path,body", OPERATOR_ROUTES)
async def test_anonymous_gets_401_or_403_on_every_operator_route(client, method, path, body):
    r = await client.request(method, path, json=body)
    assert r.status_code in (401, 403), (method, path, r.status_code)


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/webhooks?url=http://insecure.example/hook"),  # 422: not https
        ("DELETE", "/api/webhooks?url=http://insecure.example/hook"),
        ("POST", "/api/alerts/999/acknowledge"),  # 404: no such alert
    ],
)
async def test_operator_passes_the_role_check(client, operator_headers, method, path):
    r = await client.request(method, path, headers=operator_headers)
    assert r.status_code != 403, (method, path, r.text)


async def test_a_token_claiming_operator_for_a_viewer_row_is_still_a_viewer(client, make_user, session_maker):
    """Role comes from the database row, not from the (client-visible) token claim."""
    import api.auth as auth_module

    user, _ = await make_user("claims_op", "viewer")
    forged = auth_module.create_access_token(user.id, "operator")
    r = await client.post("/api/alerts/1/acknowledge", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 403


async def _seed_alerts(session_maker, n):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with session_maker() as s:
        for i in range(n):
            s.add(
                Alert(
                    score=float(i),
                    alert=True,
                    type="thermal_spike",
                    message=f"m{i}",
                    severity="WARNING",
                    created_at=base + timedelta(minutes=i),
                )
            )
        await s.commit()


async def test_two_operators_produce_distinct_acknowledged_by_and_audit_entries(client, make_user, session_maker):
    _, alice = await make_user("alice", "operator")
    _, bob = await make_user("bob", "operator")
    await _seed_alerts(session_maker, 2)

    a = (await client.post("/api/alerts/1/acknowledge", headers=alice)).json()
    b = (await client.post("/api/alerts/2/acknowledge", headers=bob)).json()
    assert {a["acknowledged_by"], b["acknowledged_by"]} == {"alice", "bob"}

    async with session_maker() as s:
        logs = (await s.execute(select(AuditLog).where(AuditLog.action == "alert_acknowledged"))).scalars().all()
    assert len(logs) == 2 and len({log.user_id for log in logs}) == 2
