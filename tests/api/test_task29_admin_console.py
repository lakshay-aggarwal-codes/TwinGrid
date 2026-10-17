"""Task 29: the admin console (api/plugins/admin_console.py), through the real app.

The permission matrix covers EVERY route: no token, viewer and operator are refused (403) and change nothing; an admin is
served. Webhook tests never send a request (``requests.post`` and DNS are replaced)."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from api.services import webhook_security, webhook_service
from models.db_models import AuditLog, User
from src import webhook_deliveries, webhook_registry
from src.admin_console import rules

UNAUTH = (401, 403)
SECRET_URL = "https://hooks.example.com/services/T000/B000/SECRETTOKEN123?key=QUERYSECRET"
WID = rules.webhook_id(SECRET_URL)


# ------------------------------------------------------------------------------------------ fixtures
@pytest.fixture
async def admin_headers(make_user):
    _, headers = await make_user("admin1", "admin")
    return headers


@pytest.fixture
def hooks(tmp_path, monkeypatch):
    """An empty webhook registry and delivery log in a temp dir; DNS answers a public address; nothing is sent."""
    monkeypatch.setattr(webhook_registry, "REGISTRY_PATH", tmp_path / "webhooks.json")
    monkeypatch.setattr(webhook_deliveries, "LOG_PATH", tmp_path / "deliveries.json")
    monkeypatch.setattr(webhook_security, "_resolve_host", lambda host, port: ["93.184.216.34"])
    sent: list[dict] = []

    class Resp:
        def __init__(self, code):
            self.status_code = code

    def post(url, json=None, timeout=None, allow_redirects=None):
        sent.append({"url": url, "json": json, "allow_redirects": allow_redirects})
        return Resp(post.code)

    post.code = 200
    monkeypatch.setattr(webhook_service.requests, "post", post)
    post.sent = sent
    return post


async def audit_rows(session_maker, action: str) -> list[AuditLog]:
    async with session_maker() as s:
        return list(
            (await s.execute(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id))).scalars()
        )


async def add_audit(session_maker, **kw) -> int:
    async with session_maker() as s:
        row = AuditLog(**{"created_at": datetime.now(timezone.utc), "outcome": "success", **kw})
        s.add(row)
        await s.commit()
        return row.id


# ------------------------------------------------------------------------------------------ permission matrix
ROUTES = [
    ("GET", "/api/admin/users", None),
    ("POST", "/api/admin/users/1/role", {"role": "admin"}),
    ("GET", "/api/admin/audit", None),
    ("GET", "/api/admin/audit/export", None),
    ("GET", "/api/admin/webhooks", None),
    ("POST", "/api/admin/webhooks", {"url": "https://hooks.example.com/x"}),
    ("PUT", f"/api/admin/webhooks/{WID}", {"url": "https://hooks.example.com/y"}),
    ("DELETE", f"/api/admin/webhooks/{WID}", None),
    ("POST", f"/api/admin/webhooks/{WID}/test", None),
    ("GET", "/api/admin/webhooks/deliveries", None),
    ("GET", "/api/admin/system", None),
]


@pytest.mark.parametrize("method,url,body", ROUTES)
async def test_no_token_is_refused(client, method, url, body):
    r = await client.request(method, url, json=body)
    assert r.status_code in UNAUTH


@pytest.mark.parametrize("who", ["viewer", "operator"])
@pytest.mark.parametrize("method,url,body", ROUTES)
async def test_a_non_admin_gets_403_and_nothing_changes(
    client, make_user, session_maker, hooks, who, method, url, body
):
    user, headers = await make_user(f"{who}-x", who)
    webhook_registry.register(SECRET_URL)
    r = await client.request(method, url, json=body, headers=headers)
    assert r.status_code == 403
    assert r.json()["detail"] == "Admin role required" and r.json()["type"] == "urn:twingrid:error:forbidden"
    assert webhook_registry.list_subscribers() == [SECRET_URL]  # untouched
    assert webhook_deliveries.recent(10) == []  # no test-fire went out
    assert hooks.sent == []
    async with session_maker() as s:
        assert (await s.get(User, user.id)).role == who
    denied = await audit_rows(session_maker, "permission_denied")
    assert denied and denied[-1].outcome == "denied" and denied[-1].details["required_role"] == "admin"
    assert denied[-1].details["actual_role"] == who


@pytest.mark.parametrize("method,url,body", [r for r in ROUTES if r[0] == "GET" and "export" not in r[1]])
async def test_an_admin_is_served_every_read(client, admin_headers, hooks, method, url, body):
    assert (await client.request(method, url, headers=admin_headers)).status_code == 200


# ------------------------------------------------------------------------------------------ users and roles
async def test_users_list_has_no_password_material_and_marks_you(client, admin_headers, make_user):
    await make_user("alice", "viewer")
    await make_user("bob", "operator")
    r = await client.get("/api/admin/users", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert {u["username"] for u in body["users"]} == {"admin1", "alice", "bob"}
    assert "password" not in json.dumps(body).lower() and "hash" not in json.dumps(body).lower()
    assert body["counts"] == {"viewer": 1, "operator": 1, "admin": 1} and body["roles"] == [
        "viewer",
        "operator",
        "admin",
    ]
    assert [u["username"] for u in body["users"] if u["is_you"]] == ["admin1"]
    assert body["truncated"] is False


async def test_changing_a_role_applies_at_once_and_is_audited(client, admin_headers, make_user, session_maker):
    target, target_headers = await make_user("carol", "viewer")
    before = await client.get("/api/admin/users", headers=target_headers)
    assert before.status_code == 403
    r = await client.post(f"/api/admin/users/{target.id}/role", json={"role": "admin"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["role"] == "admin"
    # the role is read from the database on every request: the same token now opens the console
    assert (await client.get("/api/admin/users", headers=target_headers)).status_code == 200
    (row,) = await audit_rows(session_maker, "user_role_changed")
    assert row.outcome == "success" and row.username == "admin1" and row.resource_type == "user"
    assert row.resource_id == str(target.id) and row.details == {"username": "carol", "from": "viewer", "to": "admin"}


async def test_demoting_works_and_the_demoted_user_is_locked_out_again(client, admin_headers, make_user):
    target, target_headers = await make_user("dave", "admin")
    r = await client.post(f"/api/admin/users/{target.id}/role", json={"role": "viewer"}, headers=admin_headers)
    assert r.status_code == 200
    assert (await client.get("/api/admin/users", headers=target_headers)).status_code == 403


async def test_refused_role_changes_write_nothing(client, make_user, admin_headers, session_maker):
    me = next(u for u in (await client.get("/api/admin/users", headers=admin_headers)).json()["users"] if u["is_you"])
    other, _ = await make_user("erin", "operator")
    own = await client.post(f"/api/admin/users/{me['id']}/role", json={"role": "viewer"}, headers=admin_headers)
    assert own.status_code == 409 and own.json()["type"] == "urn:twingrid:error:own_role"
    same = await client.post(f"/api/admin/users/{other.id}/role", json={"role": "operator"}, headers=admin_headers)
    assert same.status_code == 409 and same.json()["type"] == "urn:twingrid:error:unchanged"
    assert (
        await client.post("/api/admin/users/99999/role", json={"role": "admin"}, headers=admin_headers)
    ).status_code == 404
    for bad in ({"role": "root"}, {"role": ""}, {}, {"role": "admin", "extra": 1}):
        assert (
            await client.post(f"/api/admin/users/{other.id}/role", json=bad, headers=admin_headers)
        ).status_code == 422
    assert (
        await client.post("/api/admin/users/0/role", json={"role": "admin"}, headers=admin_headers)
    ).status_code == 422
    assert await audit_rows(session_maker, "user_role_changed") == []
    async with session_maker() as s:
        assert (await s.get(User, other.id)).role == "operator"


# ------------------------------------------------------------------------------------------ audit log viewer
@pytest.fixture
async def seeded_audit(session_maker):
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    ids = []
    for i, (action, outcome, username, rtype) in enumerate(
        [
            ("login_failure", "failure", "=cmd|' /C calc'!A0", None),
            ("login_success", "success", "alice", None),
            ("webhook_registered", "success", "alice", "webhook"),
            ("permission_denied", "denied", "bob", "endpoint"),
            ("login_failure", "failure", "mallory", None),
        ]
    ):
        ids.append(
            await add_audit(
                session_maker,
                action=action,
                outcome=outcome,
                username=username,
                resource_type=rtype,
                created_at=t0 + timedelta(hours=i),
                details={"n": i},
                client_ip="10.0.0.1",
            )
        )
    return ids


async def test_audit_lists_newest_first_with_the_fields_an_admin_needs(client, admin_headers, seeded_audit):
    r = await client.get("/api/admin/audit", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    ids = [i["id"] for i in body["items"]]
    assert ids == sorted(ids, reverse=True) and ids[:5] == list(reversed(seeded_audit))
    first = body["items"][0]
    assert set(first) == {
        "id",
        "created_at",
        "username",
        "action",
        "outcome",
        "resource_type",
        "resource_id",
        "client_ip",
        "request_id",
        "details",
    }
    assert {"login_failure", "permission_denied"} <= set(body["actions"]) and body["outcomes"] == [
        "success",
        "denied",
        "failure",
    ]


@pytest.mark.parametrize(
    "params,count",
    [
        ({"action": "login_failure"}, 2),
        ({"outcome": "denied"}, 1),
        ({"username": "alice"}, 2),
        ({"resource_type": "webhook"}, 1),
        ({"action": "login_failure", "username": "mallory"}, 1),
        ({"since": "2026-01-01T14:00:00+00:00"}, 3),
        ({"until": "2026-01-01T13:00:00+00:00"}, 2),
        ({"since": "2026-01-01T13:00:00+00:00", "until": "2026-01-01T14:00:00+00:00"}, 2),
        ({"action": "nothing_like_this"}, 0),
    ],
)
async def test_audit_filters(client, admin_headers, seeded_audit, params, count):
    r = await client.get("/api/admin/audit", params=params, headers=admin_headers)
    assert r.status_code == 200 and len(r.json()["items"]) == count


async def test_audit_paging_never_repeats_or_skips(client, admin_headers, seeded_audit):
    seen: list[int] = []
    before = None
    for _ in range(5):
        params = {"limit": 2, **({"before_id": before} if before else {})}
        body = (await client.get("/api/admin/audit", params=params, headers=admin_headers)).json()
        seen += [i["id"] for i in body["items"]]
        if not body["has_more"]:
            assert body["next_before_id"] is None
            break
        before = body["next_before_id"]
    assert seen == list(reversed(seeded_audit))


@pytest.mark.parametrize(
    "params",
    [
        {"outcome": "great"},
        {"limit": 0},
        {"limit": 201},
        {"before_id": 0},
        {"since": "not-a-date"},
        {"action": "x" * 65},
        {"since": "2026-02-01T00:00:00Z", "until": "2026-01-01T00:00:00Z"},
    ],
)
async def test_bad_audit_filters_are_422(client, admin_headers, params):
    assert (await client.get("/api/admin/audit", params=params, headers=admin_headers)).status_code == 422


async def test_a_filter_value_is_data_not_sql(client, admin_headers, seeded_audit):
    r = await client.get("/api/admin/audit", params={"username": "x' OR '1'='1"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["items"] == []


# ------------------------------------------------------------------------------------------ audit export
async def test_csv_export_neutralises_formulas_and_is_itself_audited(
    client, admin_headers, seeded_audit, session_maker
):
    r = await client.get("/api/admin/audit/export", params={"action": "login_failure"}, headers=admin_headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert re.fullmatch(r'attachment; filename="audit-log-\d{8}T\d{6}Z\.csv"', r.headers["content-disposition"])
    assert r.headers["x-export-truncated"] == "false" and r.headers["x-export-rows"] == "2"
    assert r.headers["cache-control"] == "no-store"
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == list(rules.EXPORT_COLUMNS) and len(rows) == 3
    usernames = {row[2] for row in rows[1:]}
    assert usernames == {"'=cmd|' /C calc'!A0", "mallory"}  # the formula is text in a spreadsheet
    assert not any(c.startswith(("=", "+", "-", "@")) for row in rows for c in row)
    (audit,) = await audit_rows(session_maker, "audit_exported")
    assert audit.username == "admin1" and audit.details == {
        "format": "csv",
        "rows": 2,
        "truncated": False,
        "filters": {"action": "login_failure"},
    }


async def test_json_export_and_the_row_bound(client, admin_headers, seeded_audit, monkeypatch):
    r = await client.get("/api/admin/audit/export", params={"format": "json"}, headers=admin_headers)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    data = r.json()
    assert len(data) == 5 and data[0]["username"] == "mallory"  # newest first; JSON values are exact
    monkeypatch.setattr(rules, "EXPORT_MAX_ROWS", 2)
    capped = await client.get("/api/admin/audit/export", params={"format": "json"}, headers=admin_headers)
    assert capped.headers["x-export-truncated"] == "true" and len(capped.json()) == 2


@pytest.mark.parametrize("params", [{"format": "xml"}, {"outcome": "great"}, {"since": "nope"}])
async def test_bad_export_requests_are_422_and_export_nothing(client, admin_headers, session_maker, params):
    assert (await client.get("/api/admin/audit/export", params=params, headers=admin_headers)).status_code == 422
    assert await audit_rows(session_maker, "audit_exported") == []


# ------------------------------------------------------------------------------------------ webhooks
def _no_secret(payload) -> None:
    blob = payload if isinstance(payload, str) else json.dumps(payload)
    assert "SECRETTOKEN" not in blob and "QUERYSECRET" not in blob and "/services/" not in blob


async def test_create_lists_only_id_scheme_host_port_and_audits_without_the_secret(
    client, admin_headers, hooks, session_maker
):
    r = await client.post("/api/admin/webhooks", json={"url": SECRET_URL}, headers=admin_headers)
    assert r.status_code == 200
    _no_secret(r.text)
    (hook,) = r.json()["webhooks"]
    assert hook == {"id": WID, "scheme": "https", "host": "hooks.example.com", "port": None, "last_delivery": None}
    assert webhook_registry.list_subscribers() == [SECRET_URL]  # stored whole (that is what is delivered to)...
    listing = await client.get("/api/admin/webhooks", headers=admin_headers)
    _no_secret(listing.text)  # ...but never shown
    assert listing.json()["max"] == webhook_registry.MAX_SUBSCRIBERS
    (audit,) = await audit_rows(session_maker, "webhook_registered")
    assert audit.resource_id == WID and audit.username == "admin1"
    _no_secret(audit.details)


async def test_create_refuses_duplicates_unsafe_urls_and_overflow(
    client, admin_headers, hooks, session_maker, monkeypatch
):
    assert (
        await client.post("/api/admin/webhooks", json={"url": SECRET_URL}, headers=admin_headers)
    ).status_code == 200
    assert (
        await client.post("/api/admin/webhooks", json={"url": SECRET_URL}, headers=admin_headers)
    ).status_code == 409
    for bad in (
        "http://hooks.example.com/x",
        "https://user:pw@hooks.example.com/x",
        "not a url",
        "ftp://hooks.example.com/x",
    ):
        assert (await client.post("/api/admin/webhooks", json={"url": bad}, headers=admin_headers)).status_code == 422
    monkeypatch.setattr(webhook_security, "_resolve_host", lambda host, port: ["10.1.2.3"])
    assert (
        await client.post("/api/admin/webhooks", json={"url": "https://internal.example.com/x"}, headers=admin_headers)
    ).status_code == 422
    monkeypatch.setattr(webhook_security, "_resolve_host", lambda host, port: ["93.184.216.34"])
    monkeypatch.setattr(webhook_registry, "MAX_SUBSCRIBERS", 1)
    assert (
        await client.post("/api/admin/webhooks", json={"url": "https://other.example.com/x"}, headers=admin_headers)
    ).status_code == 409
    assert await audit_rows(session_maker, "webhook_registered") == [
        r for r in await audit_rows(session_maker, "webhook_registered") if r.resource_id == WID
    ]  # the refused one wrote nothing
    assert (await client.post("/api/admin/webhooks", json={"url": ""}, headers=admin_headers)).status_code == 422
    assert (
        await client.post(
            "/api/admin/webhooks", json={"url": "https://a.example.com", "extra": 1}, headers=admin_headers
        )
    ).status_code == 422
    assert webhook_registry.list_subscribers() == [SECRET_URL]


async def test_edit_replaces_the_url_in_place_and_audits_the_change(client, admin_headers, hooks, session_maker):
    webhook_registry.register(SECRET_URL)
    new = "https://hooks2.example.com/a/NEWSECRET?t=NEWQUERYSECRET"
    r = await client.put(f"/api/admin/webhooks/{WID}", json={"url": new}, headers=admin_headers)
    assert r.status_code == 200
    (hook,) = r.json()["webhooks"]
    assert hook["id"] == rules.webhook_id(new) and hook["host"] == "hooks2.example.com"
    assert "NEWSECRET" not in r.text and "NEWQUERYSECRET" not in r.text
    assert webhook_registry.list_subscribers() == [new]
    (audit,) = await audit_rows(session_maker, "webhook_updated")
    assert audit.resource_id == WID and audit.details["from"] == WID
    assert audit.details["to"]["host"] == "hooks2.example.com" and "NEWSECRET" not in json.dumps(audit.details)


async def test_edit_refusals_change_nothing(client, admin_headers, hooks, session_maker):
    webhook_registry.register(SECRET_URL)
    other = "https://other.example.com/x"
    webhook_registry.register(other)
    assert (
        await client.put(f"/api/admin/webhooks/{WID}", json={"url": SECRET_URL}, headers=admin_headers)
    ).status_code == 409
    assert (
        await client.put(f"/api/admin/webhooks/{WID}", json={"url": other}, headers=admin_headers)
    ).status_code == 409
    assert (
        await client.put(
            f"/api/admin/webhooks/{'0' * 16}", json={"url": "https://x.example.com"}, headers=admin_headers
        )
    ).status_code == 404
    assert (
        await client.put(f"/api/admin/webhooks/{WID}", json={"url": "http://x.example.com"}, headers=admin_headers)
    ).status_code == 422
    assert (
        await client.put("/api/admin/webhooks/not-an-id", json={"url": "https://x.example.com"}, headers=admin_headers)
    ).status_code == 422
    assert webhook_registry.list_subscribers() == [SECRET_URL, other]
    assert await audit_rows(session_maker, "webhook_updated") == []


async def test_delete_removes_it_and_audits(client, admin_headers, hooks, session_maker):
    webhook_registry.register(SECRET_URL)
    r = await client.delete(f"/api/admin/webhooks/{WID}", headers=admin_headers)
    assert r.status_code == 200 and r.json()["webhooks"] == []
    assert webhook_registry.list_subscribers() == []
    (audit,) = await audit_rows(session_maker, "webhook_unregistered")
    assert audit.resource_id == WID
    _no_secret(audit.details)
    assert (await client.delete(f"/api/admin/webhooks/{WID}", headers=admin_headers)).status_code == 404


async def test_test_fire_sends_a_labelled_test_event_logs_it_and_audits(client, admin_headers, hooks, session_maker):
    webhook_registry.register(SECRET_URL)
    r = await client.post(f"/api/admin/webhooks/{WID}/test", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert (
        body["ok"] is True and body["status_code"] == 200 and body["error_kind"] is None and body["webhook_id"] == WID
    )
    (sent,) = hooks.sent
    assert sent["url"] == SECRET_URL and sent["allow_redirects"] is False
    assert sent["json"]["event"] == "test" and "not an alert" in sent["json"]["note"]
    (rec,) = webhook_deliveries.recent(5)
    assert rec["kind"] == "test" and rec["ok"] is True
    (audit,) = await audit_rows(session_maker, "webhook_test_fired")
    assert audit.resource_id == WID
    _no_secret(audit.details)


async def test_a_failing_subscriber_is_a_result_not_an_api_error(client, admin_headers, hooks):
    webhook_registry.register(SECRET_URL)
    hooks.code = 500
    r = await client.post(f"/api/admin/webhooks/{WID}/test", headers=admin_headers)
    assert r.status_code == 200
    assert (r.json()["ok"], r.json()["status_code"], r.json()["error_kind"]) == (False, 500, "http_error")
    assert (await client.post(f"/api/admin/webhooks/{'0' * 16}/test", headers=admin_headers)).status_code == 404


async def test_a_target_that_became_internal_is_blocked_at_test_time(client, admin_headers, hooks, monkeypatch):
    webhook_registry.register(SECRET_URL)
    monkeypatch.setattr(webhook_security, "_resolve_host", lambda host, port: ["127.0.0.1"])
    body = (await client.post(f"/api/admin/webhooks/{WID}/test", headers=admin_headers)).json()
    assert (body["ok"], body["error_kind"]) == (False, "blocked_url") and hooks.sent == []


async def test_delivery_log_lists_real_and_test_deliveries_newest_first_without_secrets(client, admin_headers, hooks):
    webhook_registry.register(SECRET_URL)
    other = "https://other.example.com/x"
    webhook_registry.register(other)
    await webhook_service.dispatch_alert({"type": "thermal_spike", "origin": "real"})  # a real alert delivery
    await client.post(f"/api/admin/webhooks/{WID}/test", headers=admin_headers)
    r = await client.get("/api/admin/webhooks/deliveries", headers=admin_headers)
    assert r.status_code == 200
    _no_secret(r.text)
    kinds = [d["kind"] for d in r.json()["deliveries"]]
    assert kinds[0] == "test" and kinds.count("alert") == 2  # both subscribers got the alert; newest (the test) first
    only = await client.get("/api/admin/webhooks/deliveries", params={"webhook_id": WID}, headers=admin_headers)
    assert {d["webhook_id"] for d in only.json()["deliveries"]} == {WID} and len(only.json()["deliveries"]) == 2
    assert (await client.get("/api/admin/webhooks/deliveries", params={"limit": 1}, headers=admin_headers)).json()[
        "deliveries"
    ][0]["kind"] == "test"
    for bad in ({"limit": 0}, {"limit": 201}, {"webhook_id": "short"}, {"webhook_id": "G" * 16}):
        assert (
            await client.get("/api/admin/webhooks/deliveries", params=bad, headers=admin_headers)
        ).status_code == 422
    listing = (await client.get("/api/admin/webhooks", headers=admin_headers)).json()
    last = {h["id"]: h["last_delivery"] for h in listing["webhooks"]}
    assert last[WID]["kind"] == "test" and last[rules.webhook_id(other)]["kind"] == "alert"


async def test_simulated_alerts_do_not_fire_webhooks_by_default_and_the_console_says_so(
    client, admin_headers, hooks, monkeypatch
):
    monkeypatch.delenv("WEBHOOK_ON_SIMULATED", raising=False)
    webhook_registry.register(SECRET_URL)
    await webhook_service.dispatch_alert({"type": "thermal_spike", "origin": "simulated"})
    assert hooks.sent == []
    assert (await client.get("/api/admin/webhooks", headers=admin_headers)).json()[
        "fires_for_simulated_alerts"
    ] is False
    monkeypatch.setenv("WEBHOOK_ON_SIMULATED", "true")
    assert (await client.get("/api/admin/webhooks", headers=admin_headers)).json()["fires_for_simulated_alerts"] is True


# ------------------------------------------------------------------------------------------ system status
async def test_system_status_reports_components_versions_migration_uptime_and_docs(client, admin_headers):
    r = await client.get("/api/admin/system", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"readiness", "migration", "versions", "uptime", "models", "docs", "unavailable"}
    assert body["readiness"]["status"] in ("ready", "not_ready") and "checks" in body["readiness"]
    assert set(body["migration"]) == {"head", "database", "at_head"} and isinstance(body["migration"]["at_head"], bool)
    from src import versions

    assert body["versions"]["safety_envelope"] == versions.SAFETY_ENVELOPE_VERSION
    assert body["versions"]["physics"] == versions.active_physics_version()
    assert body["versions"]["app"] and body["versions"]["python"]
    assert (
        isinstance(body["uptime"]["seconds"], int) and body["uptime"]["seconds"] >= 0 and body["uptime"]["started_at"]
    )
    assert "state" in body["models"] and "registry" in body["models"]
    assert body["docs"] == {"swagger": "/docs", "redoc": "/redoc", "openapi": "/openapi.json"}
    assert isinstance(body["unavailable"], list)


async def test_system_status_leaks_no_secrets_paths_or_connection_strings(client, admin_headers):
    text = (await client.get("/api/admin/system", headers=admin_headers)).text.lower()
    for needle in (
        "postgres://",
        "postgresql",
        "sqlite:",
        "database_url",
        "jwt_secret",
        "password",
        "traceback",
        "/home/",
    ):
        assert needle not in text


async def test_the_docs_the_console_links_to_exist(client, admin_headers):
    docs = (await client.get("/api/admin/system", headers=admin_headers)).json()["docs"]
    for path in docs.values():
        assert (await client.get(path)).status_code == 200
