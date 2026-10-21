"""Task 22: the viewer workflow, end to end through the real app (in-memory SQLite, real mail adapter, no doubles).

Chain under test:  visitor requests access -> owner is mailed -> admin approves -> visitor is mailed an activation link ->
status poll says ``can_activate`` -> visitor sets a password -> signs in as a viewer -> can read, cannot write ->
the link is dead afterwards.  Also: reject, expiry of the activation link, and the read-only demo path.

Unlike ``test_access_requests.py`` (Task 9), which records mail with a double, these tests use the REAL ``src.notify.mail``
adapter with ``ACCESS_NOTIFY_BACKEND=file`` and read the activation link out of the ``.eml`` it wrote. Nothing is mocked
except the clock where a link has to be aged. No real facility data and no real addresses: every account is a test row.
"""

from __future__ import annotations

import email
import email.policy
import re
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from models.db_models import AccessRequest, AuditLog, RefreshToken, User
from src.timeutil import utc_now

PUBLIC = "/api/access-requests"
ADMIN = "/api/admin/access-requests"
VISITOR_EMAIL = "grace.hopper@example.com"
PASSWORD = "correct horse battery staple"
BASE_URL = "https://twingrid.example"


# ------------------------------------------------------------------------------------------ fixtures
@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("ACCESS_TOKEN_PEPPER", "test-pepper-0123456789abcdef-0123456789abcdef")
    monkeypatch.setenv("ACCESS_NOTIFY_OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("ACCESS_PUBLIC_BASE_URL", BASE_URL)
    monkeypatch.setenv("ACCESS_NOTIFY_BACKEND", "file")
    monkeypatch.setenv("ACCESS_NOTIFY_FILE_DIR", str(tmp_path / "outbox"))
    monkeypatch.setenv("ACCESS_NOTIFY_FROM", "twingrid@example.com")
    monkeypatch.setenv("DEMO_PUBLIC_ENABLED", "true")
    for name in ("ACCESS_REQUESTS_ENABLED", "ACCESS_REQUEST_TTL_DAYS", "ACCESS_ACTIVATION_TTL_HOURS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def outbox(tmp_path) -> Path:
    return tmp_path / "outbox"


@pytest.fixture
async def admin_headers(make_user):
    _, headers = await make_user("owner-admin", "admin")
    return headers


def _messages(outbox: Path, kind: str) -> list[email.message.EmailMessage]:
    """Parsed ``.eml`` files of one kind, oldest first (the adapter names them ``<ms>-<kind>-<hex>.eml``)."""
    if not outbox.exists():
        return []
    files = sorted(outbox.glob(f"*-{kind}-*.eml"))
    return [email.message_from_bytes(f.read_bytes(), policy=email.policy.default) for f in files]  # type: ignore[misc]


def _plain(msg: email.message.EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain",))
    assert part is not None
    return part.get_content()


def _activation_token(outbox: Path) -> str:
    """The token in the newest activation mail's link (the link carries it in the fragment, never the query)."""
    (*_, last) = _messages(outbox, "activation")
    match = re.search(re.escape(BASE_URL) + r"/activate#token=([A-Za-z0-9_\-]{43})", _plain(last))
    assert match, "activation mail has no link of the form <base>/activate#token=<43 chars>"
    return match.group(1)


async def _request(client, email_addr=VISITOR_EMAIL, name="Grace Hopper", purpose="Reviewing the TwinGrid demo"):
    resp = await client.post(PUBLIC, json={"name": name, "email": email_addr, "purpose": purpose})
    assert resp.status_code == 202, resp.text
    return resp.json()


async def _queue_item(client, admin_headers, ref):
    resp = await client.get(ADMIN, headers=admin_headers)
    assert resp.status_code == 200, resp.text
    (item,) = [i for i in resp.json()["items"] if i["ref"] == ref]
    return item


async def _status(client, ref, token):
    return await client.get(f"{PUBLIC}/{ref}/status", headers={"X-Request-Token": token})


async def _login(client, username, password):
    return await client.post("/auth/login", json={"username": username, "password": password})


def _bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def _audit_actions(session_maker) -> list[str]:
    async with session_maker() as s:
        return [r.action for r in (await s.execute(select(AuditLog).order_by(AuditLog.id))).scalars()]


# ------------------------------------------------------------------------------------------ E2E-22a: approve path
async def test_visitor_is_approved_activates_signs_in_and_is_read_only(client, session_maker, admin_headers, outbox):
    # 1. visitor asks; nothing about the account is revealed, only a ticket
    ticket = await _request(client)
    ref, status_token = ticket["ref"], ticket["status_token"]
    assert ticket["status"] == "pending"

    # 2. the owner is mailed (real adapter, file backend) and the mail has no approve/reject link
    (owner_mail,) = _messages(outbox, "owner_new_request")
    assert owner_mail["To"] == "owner@example.com"
    owner_text = _plain(owner_mail)
    assert ref in owner_text and "Grace Hopper" in owner_text
    assert "#token=" not in owner_text and "no approve or reject link" in owner_text

    # 3. while pending: polling says pending / cannot activate, sign-in as that address fails (no account yet)
    polled = (await _status(client, ref, status_token)).json()
    assert polled["status"] == "pending" and polled["can_activate"] is False
    assert (await _login(client, VISITOR_EMAIL, PASSWORD)).status_code == 401

    # 4. the admin sees it in the queue and approves
    item = await _queue_item(client, admin_headers, ref)
    assert item["status"] == "pending" and item["email"] == VISITOR_EMAIL
    approve = await client.post(f"{ADMIN}/{item['id']}/approve", headers=admin_headers, json={})
    assert approve.status_code == 200, approve.text

    # 5. the visitor is mailed an activation link; mail went to the visitor, not the owner
    (activation_mail,) = _messages(outbox, "activation")
    assert activation_mail["To"] == VISITOR_EMAIL
    token = _activation_token(outbox)
    assert token != status_token

    # 6. polling now says approved + can_activate; the queue records the mail as sent
    polled = (await _status(client, ref, status_token)).json()
    assert polled["status"] == "approved" and polled["can_activate"] is True
    after = await _queue_item(client, admin_headers, ref)
    assert after["status"] == "approved" and after["notify_state"] == "sent"

    # 7. activation: a weak password is refused WITHOUT burning the link, a good one creates the account and no session
    weak = await client.post(f"{PUBLIC}/activate", json={"token": token, "password": "short"})
    assert weak.status_code == 422 and weak.json()["error"] == "invalid_password"
    same_as_email = await client.post(f"{PUBLIC}/activate", json={"token": token, "password": VISITOR_EMAIL})
    assert same_as_email.status_code == 422  # equals the address (also >= 12 chars): policy, still not consumed
    ok = await client.post(f"{PUBLIC}/activate", json={"token": token, "password": PASSWORD})
    assert ok.status_code == 200 and ok.json() == {"status": "activated"}
    assert "access_token" not in ok.text and "refresh_token" not in ok.text  # activation issues no session

    # 8. the link works once
    replay = await client.post(f"{PUBLIC}/activate", json={"token": token, "password": PASSWORD})
    assert replay.status_code == 400 and replay.json() == {"error": "invalid_or_expired"}
    assert (await _status(client, ref, status_token)).json()["status"] == "activated"

    # 9. the visitor signs in with the approved address and is a viewer
    login = await _login(client, VISITOR_EMAIL, PASSWORD)
    assert login.status_code == 200, login.text
    assert login.json()["role"] == "viewer"
    assert (await _login(client, VISITOR_EMAIL, PASSWORD + "!")).status_code == 401
    headers = _bearer(login.json()["access_token"])

    # 10. a viewer can read and cannot write or reach the admin queue
    assert (await client.get("/api/alerts", headers=headers)).status_code == 200
    assert (await client.post("/api/optimize", headers=headers, json={})).status_code == 403
    assert (await client.get(ADMIN, headers=headers)).status_code == 403

    # 11. the stored account is a viewer, the password is hashed, and the request points at it
    async with session_maker() as s:
        user = (await s.execute(select(User).where(User.username == VISITOR_EMAIL))).scalar_one()
        row = (await s.execute(select(AccessRequest).where(AccessRequest.ref == ref))).scalar_one()
    assert user.role == "viewer" and user.hashed_password != PASSWORD and PASSWORD not in user.hashed_password
    assert row.user_id == user.id and row.activation_token_hash is None

    # 12. the audit trail has the whole story, and no secret is in any row
    actions = await _audit_actions(session_maker)
    for expected in (
        "access_request_created",
        "access_request_approved",
        "access_request_activated",
        "login_success",
    ):
        assert expected in actions, f"missing audit action {expected}: {actions}"
    async with session_maker() as s:
        blob = " ".join(
            f"{r.action} {r.resource_id} {r.details}" for r in (await s.execute(select(AuditLog))).scalars()
        )
    for secret in (token, status_token, PASSWORD):
        assert secret not in blob


async def test_status_and_activation_tokens_are_separate_secrets(client, admin_headers, outbox):
    ticket = await _request(client)
    # wrong token and unknown ref are the same 404, so a ref alone proves nothing
    wrong = await _status(client, ticket["ref"], "x" * 43)
    unknown = await _status(client, "ZZZZZZZZZZZZ", ticket["status_token"])
    assert wrong.status_code == unknown.status_code == 404 and wrong.json() == unknown.json()
    # an activation token cannot be guessed from the status token
    bad = await client.post(f"{PUBLIC}/activate", json={"token": ticket["status_token"], "password": PASSWORD})
    assert bad.status_code == 400 and bad.json() == {"error": "invalid_or_expired"}
    assert _messages(outbox, "activation") == []


# ------------------------------------------------------------------------------------------ E2E-22b: reject path
async def test_rejected_visitor_gets_no_link_and_no_account(client, session_maker, admin_headers, outbox):
    ticket = await _request(client, email_addr="rejected.visitor@example.com", name="Rae Jected")
    item = await _queue_item(client, admin_headers, ticket["ref"])
    resp = await client.post(f"{ADMIN}/{item['id']}/reject", headers=admin_headers, json={"note": "not a fit"})
    assert resp.status_code == 200, resp.text

    polled = (await _status(client, ticket["ref"], ticket["status_token"])).json()
    assert polled["status"] == "rejected" and polled["can_activate"] is False
    assert _messages(outbox, "activation") == []  # a rejection never carries a link
    for mail in _messages(outbox, "rejected"):
        assert "#token=" not in _plain(mail)
    assert (await _login(client, "rejected.visitor@example.com", PASSWORD)).status_code == 401
    async with session_maker() as s:
        assert (await s.execute(select(User).where(User.username == "rejected.visitor@example.com"))).first() is None
    # a decided request cannot be flipped into approval by a second click
    flip = await client.post(f"{ADMIN}/{item['id']}/approve", headers=admin_headers, json={})
    assert flip.status_code == 409


# ------------------------------------------------------------------------------------------ E2E-22c: link lifetime
async def test_an_expired_activation_link_is_refused_and_a_resend_gets_a_working_one(
    client, session_maker, admin_headers, outbox
):
    ticket = await _request(client, email_addr="late.visitor@example.com", name="Lee Tate")
    item = await _queue_item(client, admin_headers, ticket["ref"])
    assert (await client.post(f"{ADMIN}/{item['id']}/approve", headers=admin_headers, json={})).status_code == 200
    old_token = _activation_token(outbox)

    async with session_maker() as s:  # age the link past its TTL
        row = (await s.execute(select(AccessRequest).where(AccessRequest.id == item["id"]))).scalar_one()
        row.activation_expires_at = utc_now() - timedelta(minutes=1)
        await s.commit()
    expired = await client.post(f"{PUBLIC}/activate", json={"token": old_token, "password": PASSWORD})
    assert expired.status_code == 400 and expired.json() == {
        "error": "invalid_or_expired"
    }  # same body as any bad token

    # the visitor asks for a new link with their ticket; the answer is the same whatever the state
    resend = await client.post(
        f"{PUBLIC}/resend-activation", json={"ref": ticket["ref"], "status_token": ticket["status_token"]}
    )
    assert resend.status_code == 202
    new_token = _activation_token(outbox)
    assert new_token != old_token
    assert (await client.post(f"{PUBLIC}/activate", json={"token": old_token, "password": PASSWORD})).status_code == 400
    done = await client.post(f"{PUBLIC}/activate", json={"token": new_token, "password": PASSWORD})
    assert done.status_code == 200
    assert (await _login(client, "late.visitor@example.com", PASSWORD)).status_code == 200


async def test_resend_before_approval_sends_nothing_and_answers_like_any_resend(client, outbox):
    ticket = await _request(client, email_addr="eager.visitor@example.com", name="Ed Ger")
    resend = await client.post(
        f"{PUBLIC}/resend-activation", json={"ref": ticket["ref"], "status_token": ticket["status_token"]}
    )
    nobody = await client.post(f"{PUBLIC}/resend-activation", json={"ref": "ZZZZZZZZZZZZ", "status_token": "y" * 43})
    assert resend.status_code == nobody.status_code == 202 and resend.json() == nobody.json()
    assert _messages(outbox, "activation") == []


# ------------------------------------------------------------------------------------------ E2E-22d: demo path
async def test_demo_visitor_can_read_but_never_write_and_has_no_refresh_token(client, session_maker, make_user):
    await make_user("demo_viewer", "viewer")  # the account the demo session is minted for (seeded in a real deploy)
    resp = await client.post("/auth/demo-session")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["demo"] is True and body["role"] == "viewer" and "refresh_token" not in body
    headers = _bearer(body["access_token"])

    assert (await client.get("/api/alerts", headers=headers)).status_code == 200
    blocked = await client.post("/api/optimize", headers=headers, json={})
    assert blocked.status_code == 403
    assert "read-only" in blocked.text.lower() and "demo_read_only" in blocked.text
    # a demo session cannot be extended
    refresh = await client.post("/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert refresh.status_code == 401
    async with session_maker() as s:
        assert (await s.execute(select(RefreshToken))).first() is None


async def test_a_real_viewer_is_not_mistaken_for_a_demo_visitor(client, session_maker, admin_headers, outbox):
    """The demo guard keys on the ``demo`` claim: an approved visitor's token must not carry it."""
    import api.auth as auth

    ticket = await _request(client, email_addr="real.viewer@example.com", name="Rea Viewer")
    item = await _queue_item(client, admin_headers, ticket["ref"])
    await client.post(f"{ADMIN}/{item['id']}/approve", headers=admin_headers, json={})
    token = _activation_token(outbox)
    await client.post(f"{PUBLIC}/activate", json={"token": token, "password": PASSWORD})
    login = await _login(client, "real.viewer@example.com", PASSWORD)
    claims = auth.decode_token(login.json()["access_token"])
    assert not auth.is_demo_claims(claims) and claims.get("role") == "viewer"
