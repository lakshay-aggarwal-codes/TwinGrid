"""Task 13: ``POST /auth/demo-session`` and the demo read-only guard (roadmap section 8.3).

Real app, in-memory SQLite (tests/api/conftest.py). Nothing here uses a real facility; every account is a test row.
"""

from __future__ import annotations

import inspect
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from jose import jwt
from sqlalchemy import func, select

import api.auth as auth
from api.demo_guard import ALLOWED_DEMO_WRITES, WRITE_METHODS, require_not_demo
from api.errors import ApiError
from api.main import app
from api.plugins import copilot as copilot_plugin
from api.plugins import demo_session
from api.rate_limit import limiter
from models.db_models import AuditLog, Base, RefreshToken
from src.copilot import tools as copilot_tools

PATH = "/auth/demo-session"


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("DEMO_PUBLIC_ENABLED", "true")


@pytest.fixture
async def demo_viewer(make_user):
    return await make_user("demo_viewer", "viewer")


async def _issue(client) -> dict:
    r = await client.post(PATH)
    assert r.status_code == 200, r.text
    return r.json()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _claims(token: str) -> dict:
    return jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])


# ----------------------------------------------------------------------------- switch and account
@pytest.mark.parametrize("value", [None, "", "false", "0", "no"])
async def test_disabled_is_a_404_identical_to_an_unknown_route(client, monkeypatch, demo_viewer, value):
    if value is None:
        monkeypatch.delenv("DEMO_PUBLIC_ENABLED", raising=False)
    else:
        monkeypatch.setenv("DEMO_PUBLIC_ENABLED", value)
    real = await client.post(PATH)
    unknown = await client.post("/auth/no-such-route")
    assert real.status_code == unknown.status_code == 404
    strip = lambda r: {k: v for k, v in r.json().items() if k not in ("instance", "request_id")}  # noqa: E731
    assert strip(real) == strip(unknown)
    assert real.json()["type"] == "urn:twingrid:error:not_found"


async def test_missing_account_is_503_demo_unavailable(client, enabled):
    r = await client.post(PATH)
    assert r.status_code == 503
    assert r.json()["type"] == "urn:twingrid:error:demo_unavailable"


async def test_a_promoted_demo_account_is_never_handed_out(client, enabled, make_user):
    await make_user("demo_viewer", "operator")
    assert (await client.post(PATH)).status_code == 503


# ----------------------------------------------------------------------------- the token
async def test_enabled_issues_a_30_minute_read_only_viewer_token(client, enabled, demo_viewer):
    user, _ = demo_viewer
    before = time.time()
    body = await _issue(client)
    assert body["token_type"] == "bearer" and body["expires_in"] == 1800
    assert body["role"] == "viewer" and body["demo"] is True
    claims = _claims(body["access_token"])
    assert claims["sub"] == str(user.id) and claims["role"] == "viewer" and claims["demo"] is True
    assert 1790 <= claims["exp"] - before <= 1810


async def test_no_refresh_token_is_issued_or_stored(client, session_maker, enabled, demo_viewer):
    body = await _issue(client)
    assert "refresh_token" not in body
    async with session_maker() as s:
        assert (await s.execute(select(func.count()).select_from(RefreshToken))).scalar_one() == 0


async def test_the_session_is_audited(client, session_maker, enabled, demo_viewer):
    await _issue(client)
    async with session_maker() as s:
        rows = (await s.execute(select(AuditLog).where(AuditLog.action == "demo_session_issued"))).scalars().all()
    assert len(rows) == 1


async def test_session_minutes_is_configurable_and_bounded(client, monkeypatch, enabled, demo_viewer):
    monkeypatch.setenv("DEMO_SESSION_MINUTES", "5")
    assert (await _issue(client))["expires_in"] == 300
    monkeypatch.setenv("DEMO_SESSION_MINUTES", "banana")
    assert (await _issue(client))["expires_in"] == 1800


async def test_rate_limited_per_ip(client, monkeypatch, enabled, demo_viewer):
    monkeypatch.setenv("DEMO_SESSION_RATE_LIMIT", "2/hour")
    ip = f"fixed-{uuid.uuid4()}"
    monkeypatch.setattr(demo_session, "client_ip", lambda _request: ip)
    monkeypatch.setattr(limiter, "enabled", True)
    assert (await client.post(PATH)).status_code == 200
    assert (await client.post(PATH)).status_code == 200
    third = await client.post(PATH)
    assert third.status_code == 429
    assert third.json()["type"] == "urn:twingrid:error:rate_limited" and "retry-after" in third.headers
    monkeypatch.setattr(demo_session, "client_ip", lambda _request: f"other-{uuid.uuid4()}")
    assert (await client.post(PATH)).status_code == 200  # another address is not affected


# ----------------------------------------------------------------------------- what a demo token can and cannot do
async def test_a_demo_token_can_read(client, enabled, demo_viewer):
    token = (await _issue(client))["access_token"]
    assert (await client.get("/api/scenarios", headers=_bearer(token))).status_code == 200


async def test_a_demo_token_cannot_reach_the_admin_console(client, enabled, demo_viewer):
    token = (await _issue(client))["access_token"]
    for path in ("/api/admin/users", "/api/admin/audit", "/api/admin/webhooks"):
        assert (await client.get(path, headers=_bearer(token))).status_code == 403, path


async def test_a_demo_token_cannot_start_a_run_a_normal_viewer_is_not_blocked(client, enabled, demo_viewer, make_user):
    token = (await _issue(client))["access_token"]
    denied = await client.post("/api/runs", json={"scenario_id": "x"}, headers=_bearer(token))
    assert denied.status_code == 403 and denied.json()["type"] == "urn:twingrid:error:demo_read_only"
    _, headers = await make_user("plain_viewer", "viewer")
    allowed = await client.post("/api/runs", json={"scenario_id": "x"}, headers=headers)
    assert allowed.status_code != 403 or allowed.json()["type"] != "urn:twingrid:error:demo_read_only"


def _write_routes() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path, item in app.openapi()["paths"].items():
        for method in item:
            if method.upper() in WRITE_METHODS and path not in ALLOWED_DEMO_WRITES:
                found.append((method.upper(), path))
    return sorted(found)


WRITE_ROUTES = _write_routes()


def test_the_write_route_list_is_not_empty():
    assert ("POST", "/api/runs") in WRITE_ROUTES
    assert len(WRITE_ROUTES) >= 10


@pytest.mark.parametrize("method,path", WRITE_ROUTES)
async def test_a_demo_token_gets_403_demo_read_only_on_every_write_route(client, enabled, demo_viewer, method, path):
    token = (await _issue(client))["access_token"]
    url = _fill(path)
    r = await client.request(method, url, headers=_bearer(token))
    assert r.status_code == 403, (method, path, r.text)
    assert r.json()["type"] == "urn:twingrid:error:demo_read_only"


def _fill(path: str) -> str:
    out, i = [], 0
    while i < len(path):
        if path[i] == "{":
            j = path.index("}", i)
            out.append("1")
            i = j + 1
        else:
            out.append(path[i])
            i += 1
    return "".join(out)


async def test_the_dependency_alone_denies_a_demo_claim():
    with pytest.raises(ApiError) as exc:
        await require_not_demo({"sub": "1", "demo": True})
    assert exc.value.status_code == 403 and exc.value.code == "demo_read_only"
    assert await require_not_demo({"sub": "1"}) is None
    assert await require_not_demo({"sub": "1", "demo": "true"}) is None  # only the JSON boolean counts


def test_is_demo_claims_is_strict():
    assert auth.is_demo_claims({"demo": True}) is True
    for claims in ({}, {"demo": False}, {"demo": "true"}, {"demo": 1}, {"demo": None}):
        assert auth.is_demo_claims(claims) is False


# ----------------------------------------------------------------------------- tokens that are not demo tokens
async def test_an_unsigned_or_expired_demo_claim_is_a_401_not_a_demo_403(client, enabled, demo_viewer):
    user, _ = demo_viewer
    forged = jwt.encode({"sub": str(user.id), "demo": True, "exp": time.time() + 600}, "wrong-key", algorithm="HS256")
    expired = jwt.encode(
        {"sub": str(user.id), "demo": True, "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        auth.SECRET_KEY,
        algorithm=auth.ALGORITHM,
    )
    for token in (forged, expired):
        r = await client.post("/api/runs", json={"scenario_id": "x"}, headers=_bearer(token))
        assert r.status_code == 401


async def test_the_few_allowed_writes_stay_open_to_a_demo_token(client, enabled, demo_viewer):
    token = (await _issue(client))["access_token"]
    for path in ("/auth/refresh", "/auth/logout"):
        r = await client.post(path, json={"refresh_token": token}, headers=_bearer(token))
        assert r.status_code in (204, 401), (path, r.status_code)


# ----------------------------------------------------------------------------- refresh / logout behave sensibly
async def test_a_demo_session_has_nothing_to_refresh(client, enabled, demo_viewer):
    body = await _issue(client)
    for candidate in (body["access_token"], "not-a-real-refresh-token"):
        r = await client.post("/auth/refresh", json={"refresh_token": candidate})
        assert r.status_code == 401


async def test_logout_is_a_no_op_for_a_demo_token(client, enabled, demo_viewer):
    body = await _issue(client)
    r = await client.post("/auth/logout", json={"refresh_token": body["access_token"]})
    assert r.status_code == 204


# ----------------------------------------------------------------------------- Task 3: assistant open, writes closed
ASK = "/api/copilot/ask"
T13_FRAGMENT = Path(__file__).resolve().parents[1] / "authz_matrix.d" / "T13.yaml"
ASK_BODY = {"question": "What does the temperature signal mean?", "context": {"kind": "general"}}


def _t13_rows() -> list[dict]:
    return yaml.safe_load(T13_FRAGMENT.read_text(encoding="utf-8"))["routes"]


async def _row_counts(session_maker) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with session_maker() as s:
        for table in Base.metadata.sorted_tables:
            counts[table.name] = (await s.execute(select(func.count()).select_from(table))).scalar_one()
    return counts


async def test_a_demo_token_can_ask_the_assistant(client, enabled, demo_viewer):
    token = (await _issue(client))["access_token"]
    r = await client.post(ASK, json=ASK_BODY, headers=_bearer(token))
    assert r.status_code == 200, r.text
    assert r.json()["mode"] in ("rule_based", "llm")


async def test_a_demo_ask_changes_no_row_in_any_table(client, session_maker, enabled, demo_viewer):
    token = (await _issue(client))["access_token"]
    before = await _row_counts(session_maker)
    assert (await client.post(ASK, json=ASK_BODY, headers=_bearer(token))).status_code == 200
    assert await _row_counts(session_maker) == before


def test_the_ask_route_is_the_only_assistant_path_open_to_demo_and_has_no_write_tool():
    assert ASK in ALLOWED_DEMO_WRITES
    assert not [p for p in ALLOWED_DEMO_WRITES if "copilot" in p and p != ASK]
    for name in copilot_tools.TOOLS:
        assert not any(w in name for w in ("write", "create", "update", "delete", "set_", "ack", "approve")), name
    source = inspect.getsource(copilot_plugin)
    for banned in (".add(", ".commit(", ".delete(", "insert(", "update("):
        assert banned not in source, banned


def test_the_t13_fragment_marks_exactly_the_guarded_write_routes_as_demo_403():
    rows = _t13_rows()
    in_yaml = {(r["method"], r["path_template"]) for r in rows if r.get("demo") == 403}
    assert in_yaml == set(WRITE_ROUTES), {
        "in_yaml_only": sorted(in_yaml - set(WRITE_ROUTES)),
        "in_openapi_only": sorted(set(WRITE_ROUTES) - in_yaml),
    }
    ask = [r for r in rows if r["path_template"] == ASK]
    assert len(ask) == 1 and ask[0]["demo"] != 403  # passes the guard (the probe body is invalid: 422)


async def test_every_t13_demo_403_route_is_denied_and_the_ask_route_is_not(client, enabled, demo_viewer):
    token = (await _issue(client))["access_token"]
    denied = [(r["method"], r["path_template"]) for r in _t13_rows() if r.get("demo") == 403]
    assert len(denied) >= 10
    for method, path in denied:
        r = await client.request(method, _fill(path), headers=_bearer(token))
        assert r.status_code == 403 and r.json()["type"] == "urn:twingrid:error:demo_read_only", (method, path)
    probe = await client.post(ASK, json={}, headers=_bearer(token))  # invalid body: validation, not the demo guard
    assert probe.status_code == 422, probe.text
