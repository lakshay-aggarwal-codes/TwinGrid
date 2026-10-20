"""Task 9: visitor access requests (contract 8.1), through the real app with an in-memory SQLite database.

Mail is never sent: ``service.deliver`` is replaced by a recorder (a TEST DOUBLE that lives only here). Tokens, passwords and
addresses are asserted to be absent from audit rows and captured logs."""

from __future__ import annotations

import logging
import re
import sys
from datetime import timedelta

import pytest
from sqlalchemy import select, text

from api.rate_limit import limiter
from api.services import audit_service
from models.db_models import AccessRequest, AuditLog, RefreshToken, User
from src.access import rules, service, tokens
from src.timeutil import utc_now

URL = "/api/access-requests"
ADMIN = "/api/admin/access-requests"
GOOD_PASSWORD = "correct horse battery staple"
ACCESS_ACTIONS = {
    "access_request_created",
    "access_request_approved",
    "access_request_rejected",
    "access_request_expired",
    "access_request_activated",
    "access_request_activation_failed",
    "access_request_notify_failed",
}


# ------------------------------------------------------------------------------------------ fixtures
@pytest.fixture
async def admin_headers(make_user):
    _, headers = await make_user("admin1", "admin")
    return headers


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ACCESS_TOKEN_PEPPER", "test-pepper-0123456789abcdef-0123456789abcdef")
    monkeypatch.setenv("ACCESS_NOTIFY_OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("ACCESS_PUBLIC_BASE_URL", "https://twingrid.example")
    for name in ("ACCESS_REQUESTS_ENABLED", "ACCESS_REQUEST_TTL_DAYS", "ACCESS_ACTIVATION_TTL_HOURS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def mails(monkeypatch):
    """Record every mail instead of sending it."""
    sent: list[tuple[str, str | None, dict]] = []

    async def fake(kind, to, ctx):
        sent.append((kind, to, dict(ctx)))
        return service.DeliveryResult(True, "ok", "console")

    monkeypatch.setattr(service, "deliver", fake)
    return sent


@pytest.fixture
def limits_on():
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.reset()  # conftest restores ``enabled``


async def submit(client, email="ada@example.com", name="Ada Lovelace", purpose="Reviewing the project"):
    return await client.post(URL, json={"name": name, "email": email, "purpose": purpose})


async def rows(session_maker, *where):
    async with session_maker() as s:
        stmt = select(AccessRequest).order_by(AccessRequest.created_at, AccessRequest.id)
        for clause in where:
            stmt = stmt.where(clause)
        return list((await s.execute(stmt)).scalars())


async def audit_rows(session_maker, action=None):
    async with session_maker() as s:
        stmt = select(AuditLog).order_by(AuditLog.id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        return list((await s.execute(stmt)).scalars())


async def set_row(session_maker, request_id, **values):
    async with session_maker() as s:
        row = (await s.execute(select(AccessRequest).where(AccessRequest.id == request_id))).scalar_one()
        for k, v in values.items():
            setattr(row, k, v)
        await s.commit()


def status_headers(token):
    return {"X-Request-Token": token}


def token_from(mails_list, kind="activation"):
    url = [ctx for k, _to, ctx in mails_list if k == kind][-1]["activation_url"]
    return url.split("#token=", 1)[1]


async def approved(client, admin_headers, mails, email="ada@example.com"):
    """Submit, approve, return (ref, status_token, request_id, activation_token)."""
    first = (await submit(client, email=email)).json()
    (row,) = [
        r
        for r in await client.get(ADMIN, headers=admin_headers)
        and (await client.get(ADMIN, headers=admin_headers)).json()["items"]
        if r["ref"] == first["ref"]
    ]
    resp = await client.post(f"{ADMIN}/{row['id']}/approve", headers=admin_headers, json={})
    assert resp.status_code == 200, resp.text
    return first["ref"], first["status_token"], row["id"], token_from(mails)


# ------------------------------------------------------------------------------------------ submit
async def test_new_submission_is_stored_and_answers_the_contract_shape(client, session_maker, mails):
    resp = await submit(client)
    assert resp.status_code == 202
    body = resp.json()
    assert set(body) == {"ref", "status", "status_token", "expires_at", "message"}
    assert re.fullmatch(r"[A-Z2-7]{12}", body["ref"]) and len(body["status_token"]) == 43
    assert body["status"] == "pending" and body["message"] == service.PUBLIC_RECEIVED_MESSAGE
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", body["expires_at"])
    (row,) = await rows(session_maker)
    assert row.ref == body["ref"] and row.status == "pending" and row.email_normalized == "ada@example.com"
    assert row.display_name == "Ada Lovelace" and row.purpose == "Reviewing the project"
    # only hashes are stored
    assert row.status_token_hash == tokens.hash_token(body["status_token"]) and len(row.status_token_hash) == 64
    assert body["status_token"] not in {str(v) for v in vars(row).values()}
    assert row.request_ip_hash == tokens.hash_ip("127.0.0.1") and "127.0.0.1" not in str(vars(row))
    ttl = row.expires_at.replace(tzinfo=None) - row.created_at.replace(tzinfo=None)
    assert ttl == timedelta(days=7)
    # the owner is told, off the request path, with the ref/name/purpose only
    assert mails == [
        (
            "owner_new_request",
            "owner@example.com",
            {"ref": row.ref, "name": "Ada Lovelace", "purpose": "Reviewing the project"},
        )
    ]
    assert (await rows(session_maker))[0].notify_state == "sent"


async def test_the_partial_unique_index_exists_and_allows_history(client, session_maker, engine):
    async with engine.connect() as conn:
        sql = (
            await conn.execute(text("SELECT sql FROM sqlite_master WHERE name='uq_access_one_pending'"))
        ).scalar_one()
    assert "UNIQUE" in sql.upper() and "status = 'pending'" in sql
    async with session_maker() as s:
        now = utc_now()

        def make(status):
            return AccessRequest(
                ref=tokens.new_ref(),
                email_normalized="x@example.com",
                display_name="X",
                status=status,
                created_at=now,
                updated_at=now,
                expires_at=now,
                status_token_hash="0" * 64,
                request_ip_hash="0" * 64,
                notify_state="pending",
                notify_attempts=0,
            )

        s.add_all([make("rejected"), make("expired"), make("pending")])
        await s.commit()
        s.add(make("pending"))
        with pytest.raises(Exception, match="UNIQUE|unique"):
            await s.commit()


async def test_normalisation_and_validation(client, session_maker, mails):
    resp = await submit(client, email="  Ada.Lovelace@Example.COM  ", name="  Ada  ", purpose="   ")
    assert resp.status_code == 202
    (row,) = await rows(session_maker)
    assert row.email_normalized == "ada.lovelace@example.com" and row.display_name == "Ada" and row.purpose is None
    too_long = "a" * 60 + "@example.com"  # 72 chars
    bad = [
        {"name": "A", "email": too_long},
        {"name": "A", "email": "not-an-email"},
        {"name": "A", "email": "a b@example.com"},
        {"name": "", "email": "a@example.com"},
        {"name": "x" * 81, "email": "a@example.com"},
        {"name": "A", "email": "a@example.com", "purpose": "p" * 501},
        {"name": "A", "email": 5},
        {"name": "A\x00", "email": "a@example.com"},
        {"email": "a@example.com"},
        ["not", "an", "object"],
    ]
    for body in bad:
        r = await client.post(URL, json=body)
        assert (r.status_code, r.json()) == (422, {"error": "invalid_request"}), body
    r = await client.post(URL, content=b"{not json", headers={"content-type": "application/json"})
    assert (r.status_code, r.json()) == (422, {"error": "invalid_request"})
    assert len(await rows(session_maker)) == 1  # nothing was stored for any invalid body


async def test_duplicate_pending_returns_the_same_ref_and_rotates_the_status_token(client, session_maker, mails):
    first = (await submit(client)).json()
    second = (await submit(client, email="ADA@example.com", name="Someone Else")).json()
    assert second["ref"] == first["ref"] and second["status_token"] != first["status_token"]
    assert set(second) == set(first)
    assert len(await rows(session_maker)) == 1
    assert (
        await client.get(f"{URL}/{first['ref']}/status", headers=status_headers(first["status_token"]))
    ).status_code == 404
    ok = await client.get(f"{URL}/{first['ref']}/status", headers=status_headers(second["status_token"]))
    assert ok.status_code == 200 and ok.json()["status"] == "pending"
    assert (await rows(session_maker))[0].display_name == "Ada Lovelace"  # the first submission's text stands
    assert len([m for m in mails if m[0] == "owner_new_request"]) == 1  # the owner is not mailed twice


async def test_existing_user_gets_a_decoy_not_a_row_and_the_same_response_shape(
    client, session_maker, make_user, mails
):
    await make_user("taken@example.com", "viewer")
    real = (await submit(client, email="fresh@example.com")).json()
    decoy_resp = await submit(client, email="Taken@Example.com")
    decoy = decoy_resp.json()
    assert decoy_resp.status_code == 202 and set(decoy) == set(real)
    assert decoy["message"] == real["message"] and decoy["status"] == "pending"
    assert re.fullmatch(r"[A-Z2-7]{12}", decoy["ref"]) and len(decoy["status_token"]) == 43
    assert [r.email_normalized for r in await rows(session_maker)] == ["fresh@example.com"]  # no row for the decoy
    assert [m[0] for m in mails] == ["owner_new_request"]  # and nobody is mailed about it
    poll = await client.get(f"{URL}/{decoy['ref']}/status", headers=status_headers(decoy["status_token"]))
    assert poll.status_code == 200
    assert poll.json()["status"] == "pending" and poll.json()["can_activate"] is False
    assert set(poll.json()) == {"ref", "status", "expires_at", "updated_at", "can_activate"}
    assert poll.json()["expires_at"] > real["expires_at"][:0]  # a real timestamp
    # same ref for the same address on the same day (as a real duplicate), a fresh token each time
    again = (await submit(client, email="taken@example.com")).json()
    assert again["ref"] == decoy["ref"] and again["status_token"] != decoy["status_token"]
    other = (await submit(client, email="taken2@example.com")).json()
    assert other["ref"] != real["ref"]
    wrong = await client.get(f"{URL}/{decoy['ref']}/status", headers=status_headers(real["status_token"]))
    assert wrong.status_code == 404


async def test_an_already_approved_address_also_gets_a_decoy(client, session_maker, admin_headers, mails):
    ref, _tok, _rid, _act = await approved(client, admin_headers, mails)
    resp = await submit(client)
    assert resp.status_code == 202 and resp.json()["ref"] != ref
    assert len(await rows(session_maker)) == 1


async def test_a_rejected_or_expired_request_does_not_block_a_new_one(client, session_maker, admin_headers, mails):
    first = (await submit(client)).json()
    (row,) = await rows(session_maker)
    r = await client.post(f"{ADMIN}/{row.id}/reject", headers=admin_headers, json={})
    assert r.status_code == 200
    second = (await submit(client)).json()
    assert second["ref"] != first["ref"]
    (pending,) = await rows(session_maker, AccessRequest.status == "pending")
    await set_row(session_maker, pending.id, expires_at=utc_now() - timedelta(seconds=1))
    third = (await submit(client)).json()
    assert third["ref"] not in (first["ref"], second["ref"])
    assert sorted(r.status for r in await rows(session_maker)) == ["expired", "pending", "rejected"]


# ------------------------------------------------------------------------------------------ status
async def test_status_for_a_real_request_and_identical_404s_otherwise(client, mails):
    body = (await submit(client)).json()
    ok = await client.get(f"{URL}/{body['ref']}/status", headers=status_headers(body["status_token"]))
    assert ok.status_code == 200
    assert ok.json() == {
        "ref": body["ref"],
        "status": "pending",
        "expires_at": body["expires_at"],
        "updated_at": ok.json()["updated_at"],
        "can_activate": False,
    }
    cases = [
        (body["ref"], {"X-Request-Token": "x" * 43}),  # right ref, wrong token
        (body["ref"], {}),  # no token
        ("ZZZZZZZZZZZZ", status_headers(body["status_token"])),  # unknown ref
        ("short", {"X-Request-Token": "x"}),
        (body["ref"], status_headers(body["status_token"][:-1])),
    ]
    seen = set()
    for ref, headers in cases:
        r = await client.get(f"{URL}/{ref}/status", headers=headers)
        seen.add((r.status_code, r.text))
    assert seen == {(404, '{"error":"not_found"}')}


async def test_status_follows_the_lifecycle_and_never_shows_the_note(client, admin_headers, session_maker, mails):
    ref, token, rid, act = await approved(client, admin_headers, mails)
    r = await client.get(f"{URL}/{ref}/status", headers=status_headers(token))
    assert r.json()["status"] == "approved" and r.json()["can_activate"] is True
    assert "decision_note" not in r.text and "note" not in r.text
    done = await client.post(f"{URL}/activate", json={"token": act, "password": GOOD_PASSWORD})
    assert done.status_code == 200
    r = await client.get(f"{URL}/{ref}/status", headers=status_headers(token))
    assert r.json()["status"] == "activated" and r.json()["can_activate"] is False


async def test_a_pending_request_expires_lazily_on_read_and_is_audited(client, session_maker, mails):
    body = (await submit(client)).json()
    (row,) = await rows(session_maker)
    await set_row(session_maker, row.id, expires_at=utc_now() - timedelta(minutes=1))
    r = await client.get(f"{URL}/{body['ref']}/status", headers=status_headers(body["status_token"]))
    assert r.json()["status"] == "expired" and r.json()["can_activate"] is False
    assert (await rows(session_maker))[0].status == "expired"
    (audit,) = await audit_rows(session_maker, "access_request_expired")
    assert audit.details["ref"] == body["ref"]


async def test_a_decoy_polls_pending_then_expired_and_a_forged_one_is_a_404(client, make_user, monkeypatch, mails):
    await make_user("taken@example.com", "viewer")
    decoy = (await submit(client, email="taken@example.com")).json()
    url = f"{URL}/{decoy['ref']}/status"
    assert (await client.get(url, headers=status_headers(decoy["status_token"]))).json()["status"] == "pending"
    forged = decoy["status_token"][:-3] + ("AAA" if not decoy["status_token"].endswith("AAA") else "BBB")
    assert (await client.get(url, headers=status_headers(forged))).status_code == 404
    later = utc_now() + timedelta(days=8)
    monkeypatch.setattr(service, "utc_now", lambda: later)
    real_status = service.status

    async def at_later(session, ref, token, now=None):
        return await real_status(session, ref, token, later)

    monkeypatch.setattr(service, "status", at_later)
    r = await client.get(url, headers=status_headers(decoy["status_token"]))
    assert r.status_code == 200 and r.json()["status"] == "expired"


# ------------------------------------------------------------------------------------------ rate limits
async def test_submit_is_limited_to_5_per_hour_per_ip(client, limits_on, mails):
    codes = [(await submit(client, email=f"user{i}@example.com")).status_code for i in range(6)]
    assert codes == [202] * 5 + [429]
    r = await submit(client, email="user9@example.com")
    assert r.status_code == 429 and "retry-after" in r.headers


async def test_submit_is_limited_to_3_per_24h_per_email(client, limits_on, mails):
    codes = [(await submit(client, email="same@example.com")).status_code for _ in range(4)]
    assert codes == [202, 202, 202, 429]
    assert (await submit(client, email="other@example.com")).status_code == 202


async def test_status_is_limited_to_60_per_minute_per_ip(client, limits_on):
    codes = [(await client.get(f"{URL}/ZZZZZZZZZZZZ/status")).status_code for _ in range(61)]
    assert codes[:60] == [404] * 60 and codes[60] == 429


async def test_resend_is_limited_to_3_per_hour_per_ip_and_always_answers_the_same(client, limits_on, mails):
    msg = {"message": "If your request is approved, a new link has been sent."}
    for _ in range(3):
        r = await client.post(f"{URL}/resend-activation", json={"ref": "ZZZZZZZZZZZZ", "status_token": "x"})
        assert (r.status_code, r.json()) == (202, msg)
    assert (
        await client.post(f"{URL}/resend-activation", json={"ref": "ZZZZZZZZZZZZ", "status_token": "x"})
    ).status_code == 429


async def test_activate_is_limited_to_10_per_hour_per_ip(client, limits_on):
    codes = [
        (await client.post(f"{URL}/activate", json={"token": "x" * 43, "password": GOOD_PASSWORD})).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [400] * 10 and codes[10] == 429


# ------------------------------------------------------------------------------------------ activation
async def test_activation_creates_a_viewer_and_issues_no_session(client, session_maker, admin_headers, mails):
    ref, _tok, rid, act = await approved(client, admin_headers, mails)
    resp = await client.post(f"{URL}/activate", json={"token": act, "password": GOOD_PASSWORD})
    assert (resp.status_code, resp.json()) == (200, {"status": "activated"})
    assert "set-cookie" not in resp.headers
    async with session_maker() as s:
        user = (await s.execute(select(User).where(User.username == "ada@example.com"))).scalar_one()
        assert (
            user.role == "viewer"
            and user.hashed_password != GOOD_PASSWORD
            and GOOD_PASSWORD not in user.hashed_password
        )
        assert (await s.execute(select(RefreshToken))).first() is None  # no session of any kind
    (row,) = await rows(session_maker, AccessRequest.id == rid)
    assert row.status == "activated" and row.user_id == user.id and row.activation_consumed_at is not None
    assert row.activation_token_hash is None
    login = await client.post("/auth/login", json={"username": "ada@example.com", "password": GOOD_PASSWORD})
    assert login.status_code == 200 and login.json().get("access_token")


async def test_every_bad_activation_token_gets_the_same_400(client, session_maker, admin_headers, mails):
    _ref, _tok, rid, act = await approved(client, admin_headers, mails)
    # replay
    assert (await client.post(f"{URL}/activate", json={"token": act, "password": GOOD_PASSWORD})).status_code == 200
    replay = await client.post(f"{URL}/activate", json={"token": act, "password": GOOD_PASSWORD})
    # a second request, approved, whose link then expires
    _r2, _t2, rid2, act2 = await approved(client, admin_headers, mails, email="bob@example.com")
    await set_row(session_maker, rid2, activation_expires_at=utc_now() - timedelta(seconds=1))
    responses = {
        "replayed": replay,
        "expired": await client.post(f"{URL}/activate", json={"token": act2, "password": GOOD_PASSWORD}),
        "unknown": await client.post(f"{URL}/activate", json={"token": tokens.new_token(), "password": GOOD_PASSWORD}),
        "malformed": await client.post(f"{URL}/activate", json={"token": "nope", "password": GOOD_PASSWORD}),
        "not_a_string": await client.post(f"{URL}/activate", json={"token": 12345, "password": GOOD_PASSWORD}),
        "missing": await client.post(f"{URL}/activate", json={"password": GOOD_PASSWORD}),
    }
    assert {(r.status_code, r.text) for r in responses.values()} == {(400, '{"error":"invalid_or_expired"}')}, {
        k: (r.status_code, r.text) for k, r in responses.items()
    }
    codes = [a.details["code"] for a in await audit_rows(session_maker, "access_request_activation_failed")]
    # a replayed token finds no row (its hash was cleared on use), so it is indistinguishable from an unknown one
    assert sorted(codes) == sorted(["unknown", "unknown", "expired", "malformed", "malformed", "malformed"])


async def test_a_status_token_is_not_an_activation_token(client, admin_headers, mails):
    _ref, status_token, _rid, _act = await approved(client, admin_headers, mails)
    r = await client.post(f"{URL}/activate", json={"token": status_token, "password": GOOD_PASSWORD})
    assert (r.status_code, r.text) == (400, '{"error":"invalid_or_expired"}')


@pytest.mark.parametrize(
    "password,reason",
    [("short", "length"), ("x" * 11, "length"), ("x" * 129, "length"), (None, "length"), ("ADA@example.com", "length")],
)
async def test_password_policy_is_enforced_and_does_not_consume_the_token(
    client, admin_headers, mails, password, reason
):
    _ref, _tok, _rid, act = await approved(client, admin_headers, mails)
    r = await client.post(f"{URL}/activate", json={"token": act, "password": password})
    assert r.status_code == 422 and r.json()["error"] == "invalid_password"
    ok = await client.post(f"{URL}/activate", json={"token": act, "password": GOOD_PASSWORD})
    assert ok.status_code == 200  # still usable


async def test_a_password_equal_to_the_email_is_refused(client, admin_headers, mails):
    _ref, _tok, _rid, act = await approved(client, admin_headers, mails, email="averylongaddress@example.com")
    r = await client.post(f"{URL}/activate", json={"token": act, "password": "AveryLongAddress@Example.com"})
    assert (r.status_code, r.json()) == (422, {"error": "invalid_password", "reason": "equals_email"})
    assert (await client.post(f"{URL}/activate", json={"token": act, "password": GOOD_PASSWORD})).status_code == 200


async def test_a_lost_compare_and_set_creates_no_account(client, session_maker, admin_headers, mails, monkeypatch):
    """Activation is single-use through a compare-and-set UPDATE: if another request consumed the token between our
    lookup and our update, the update matches no row and no account is created."""
    _ref, _tok, rid, act = await approved(client, admin_headers, mails)

    async def lost(*_a, **_k):
        return False

    monkeypatch.setattr(service, "_compare_and_set", lost)
    r = await client.post(f"{URL}/activate", json={"token": act, "password": GOOD_PASSWORD})
    assert (r.status_code, r.text) == (400, '{"error":"invalid_or_expired"}')
    async with session_maker() as s:
        assert (await s.execute(select(User).where(User.username == "ada@example.com"))).first() is None
    assert [a.details["code"] for a in await audit_rows(session_maker, "access_request_activation_failed")] == [
        "replayed"
    ]


async def test_activation_fails_cleanly_if_the_account_already_exists(
    client, session_maker, admin_headers, make_user, mails
):
    _ref, _tok, rid, act = await approved(client, admin_headers, mails)
    await make_user("ada@example.com", "operator")  # created by some other route in the meantime
    r = await client.post(f"{URL}/activate", json={"token": act, "password": GOOD_PASSWORD})
    assert (r.status_code, r.text) == (400, '{"error":"invalid_or_expired"}')
    (row,) = await rows(session_maker, AccessRequest.id == rid)
    assert row.status == "approved" and row.user_id is None  # the failed attempt changed nothing
    async with session_maker() as s:
        assert (await s.execute(select(User).where(User.username == "ada@example.com"))).scalar_one().role == "operator"


# ------------------------------------------------------------------------------------------ resend
async def test_visitor_resend_rotates_the_link_only_for_an_approved_request(client, admin_headers, mails):
    ref, status_token, _rid, old = await approved(client, admin_headers, mails)
    msg = {"message": "If your request is approved, a new link has been sent."}
    r = await client.post(f"{URL}/resend-activation", json={"ref": ref, "status_token": status_token})
    assert (r.status_code, r.json()) == (202, msg)
    new = token_from(mails)
    assert new != old
    assert (await client.post(f"{URL}/activate", json={"token": old, "password": GOOD_PASSWORD})).status_code == 400
    assert (await client.post(f"{URL}/activate", json={"token": new, "password": GOOD_PASSWORD})).status_code == 200
    # a pending request, a wrong token and an unknown ref all get the same answer and send nothing
    pending = (await submit(client, email="pending@example.com")).json()
    before = len(mails)
    for payload in (
        {"ref": pending["ref"], "status_token": pending["status_token"]},
        {"ref": ref, "status_token": "x" * 43},
        {"ref": "ZZZZZZZZZZZZ", "status_token": "x" * 43},
        {"nonsense": True},
    ):
        r = await client.post(f"{URL}/resend-activation", json=payload)
        assert (r.status_code, r.json()) == (202, msg)
    assert len(mails) == before


async def test_admin_resend_activation_rotates_and_only_when_approved(client, admin_headers, session_maker, mails):
    _ref, _tok, rid, old = await approved(client, admin_headers, mails)
    r = await client.post(f"{ADMIN}/{rid}/resend-activation", headers=admin_headers)
    assert r.status_code == 200
    new = token_from(mails)
    assert new != old
    assert (await client.post(f"{URL}/activate", json={"token": old, "password": GOOD_PASSWORD})).status_code == 400
    pending = (await submit(client, email="p@example.com")).json()
    (prow,) = await rows(session_maker, AccessRequest.ref == pending["ref"])
    assert (await client.post(f"{ADMIN}/{prow.id}/resend-activation", headers=admin_headers)).json() == {
        "error": "invalid_transition"
    }
    assert (await client.post(f"{ADMIN}/{prow.id}/resend-notification", headers=admin_headers)).status_code == 200
    assert [m[0] for m in mails].count("owner_new_request") == 3  # two submissions + the resend
    assert (await client.post(f"{ADMIN}/{rid}/resend-notification", headers=admin_headers)).status_code == 409


# ------------------------------------------------------------------------------------------ admin
ADMIN_ROUTES = [
    ("get", ADMIN),
    ("get", f"{ADMIN}/some-id"),
    ("post", f"{ADMIN}/some-id/approve"),
    ("post", f"{ADMIN}/some-id/reject"),
    ("post", f"{ADMIN}/some-id/resend-notification"),
    ("post", f"{ADMIN}/some-id/resend-activation"),
]


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
async def test_only_an_admin_may_use_the_admin_routes(client, viewer_headers, operator_headers, method, path):
    call = getattr(client, method)
    assert (await call(path)).status_code == 401
    for headers in (viewer_headers, operator_headers):
        r = await call(path, headers=headers)
        assert r.status_code == 403, (path, r.text)


async def test_non_admins_cannot_list_or_decide_and_nothing_changes(
    client, session_maker, viewer_headers, operator_headers, mails
):
    await submit(client)
    (row,) = await rows(session_maker)
    for headers in (viewer_headers, operator_headers):
        assert (await client.get(ADMIN, headers=headers)).status_code == 403
        assert (await client.post(f"{ADMIN}/{row.id}/approve", headers=headers, json={})).status_code == 403
        assert (await client.post(f"{ADMIN}/{row.id}/reject", headers=headers, json={})).status_code == 403
    (row,) = await rows(session_maker)
    assert row.status == "pending" and row.decided_by is None
    denied = [a for a in await audit_rows(session_maker, "permission_denied")]
    assert len(denied) >= 6


async def test_an_activated_viewer_cannot_elevate_or_decide(client, session_maker, admin_headers, mails):
    ref, _tok, rid, act = await approved(client, admin_headers, mails)
    await client.post(f"{URL}/activate", json={"token": act, "password": GOOD_PASSWORD})
    login = await client.post("/auth/login", json={"username": "ada@example.com", "password": GOOD_PASSWORD})
    viewer = {"Authorization": f"Bearer {login.json()['access_token']}"}
    other = (await submit(client, email="eve@example.com")).json()
    (erow,) = await rows(session_maker, AccessRequest.ref == other["ref"])
    assert (await client.post(f"{ADMIN}/{erow.id}/approve", headers=viewer, json={})).status_code == 403
    async with session_maker() as s:
        uid = (await s.execute(select(User.id).where(User.username == "ada@example.com"))).scalar_one()
    assert (
        await client.post(f"/api/admin/users/{uid}/role", headers=viewer, json={"role": "admin"})
    ).status_code == 403
    assert (await rows(session_maker, AccessRequest.id == erow.id))[0].status == "pending"


async def test_approve_reject_idempotency_and_crossed_transitions(client, session_maker, admin_headers, mails):
    await submit(client, email="a@example.com")
    await submit(client, email="b@example.com")
    ra, rb = await rows(session_maker)
    first = await client.post(f"{ADMIN}/{ra.id}/approve", headers=admin_headers, json={"note": "welcome"})
    assert (
        first.status_code == 200 and first.json()["status"] == "approved" and first.json()["decision_note"] == "welcome"
    )
    act = token_from(mails)
    again = await client.post(f"{ADMIN}/{ra.id}/approve", headers=admin_headers, json={"note": "other"})
    bookkeeping = ("notify_state", "notify_attempts")  # the activation mail finished after the first response was built
    strip = lambda d: {k: v for k, v in d.items() if k not in bookkeeping}  # noqa: E731
    assert again.status_code == 200 and strip(again.json()) == strip(first.json())  # unchanged, note included
    assert [m[0] for m in mails].count("activation") == 1  # no second mail, no second token
    assert (await client.post(f"{URL}/activate", json={"token": act, "password": GOOD_PASSWORD})).status_code == 200
    # reject
    rej = await client.post(f"{ADMIN}/{rb.id}/reject", headers=admin_headers, json={})
    assert rej.status_code == 200 and rej.json()["status"] == "rejected"
    assert (await client.post(f"{ADMIN}/{rb.id}/reject", headers=admin_headers, json={})).status_code == 200
    for path in (f"{ADMIN}/{rb.id}/approve", f"{ADMIN}/{ra.id}/reject"):  # approve-after-reject, reject-after-activate
        r = await client.post(path, headers=admin_headers, json={})
        assert (r.status_code, r.json()) == (409, {"error": "invalid_transition"})
    kinds = [m[0] for m in mails]
    assert kinds.count("rejected") == 1  # the repeat reject sends nothing more
    assert dict((m[0], m[2]) for m in mails)["rejected"] == {"name": "Ada Lovelace"}  # generic: no note, no reason


async def test_approving_an_expired_request_is_a_409_and_a_missing_one_a_404(
    client, session_maker, admin_headers, mails
):
    await submit(client)
    (row,) = await rows(session_maker)
    await set_row(session_maker, row.id, expires_at=utc_now() - timedelta(seconds=1))
    r = await client.post(f"{ADMIN}/{row.id}/approve", headers=admin_headers, json={})
    assert (r.status_code, r.json()) == (409, {"error": "invalid_transition"})
    assert (await client.post(f"{ADMIN}/does-not-exist/approve", headers=admin_headers, json={})).status_code == 404
    assert (await client.get(f"{ADMIN}/does-not-exist", headers=admin_headers)).status_code == 404


async def test_the_decision_records_who_and_when_and_a_bad_note_is_a_422(client, session_maker, admin_headers, mails):
    await submit(client)
    (row,) = await rows(session_maker)
    assert (
        await client.post(f"{ADMIN}/{row.id}/approve", headers=admin_headers, json={"note": "n" * 501})
    ).status_code == 422
    assert (
        await client.post(f"{ADMIN}/{row.id}/approve", headers=admin_headers, json={"surprise": 1})
    ).status_code == 422
    assert (await rows(session_maker))[0].status == "pending"
    r = await client.post(f"{ADMIN}/{row.id}/approve", headers=admin_headers, json={})
    assert r.status_code == 200
    (row,) = await rows(session_maker)
    async with session_maker() as s:
        admin_id = (await s.execute(select(User.id).where(User.username == "admin1"))).scalar_one()
    assert row.decided_by == admin_id == r.json()["decided_by"] and row.decided_at is not None


async def test_list_filters_pages_and_hides_the_note_in_the_list(client, session_maker, admin_headers, mails):
    for i in range(5):
        await submit(client, email=f"user{i}@example.com", name=f"User {i}")
    items = (await client.get(ADMIN, headers=admin_headers)).json()["items"]
    assert len(items) == 5
    assert set(items[0]) == {
        "id",
        "ref",
        "name",
        "email",
        "purpose",
        "status",
        "created_at",
        "expires_at",
        "decided_at",
        "decided_by",
        "notify_state",
        "notify_attempts",
    }
    await client.post(f"{ADMIN}/{items[0]['id']}/reject", headers=admin_headers, json={"note": "private reason"})
    assert "private reason" not in (await client.get(ADMIN, headers=admin_headers)).text
    assert (await client.get(f"{ADMIN}/{items[0]['id']}", headers=admin_headers)).json()[
        "decision_note"
    ] == "private reason"
    page1 = (await client.get(f"{ADMIN}?limit=2", headers=admin_headers)).json()
    assert len(page1["items"]) == 2 and page1["next_before_id"] == page1["items"][-1]["id"]
    page2 = (await client.get(f"{ADMIN}?limit=2&before_id={page1['next_before_id']}", headers=admin_headers)).json()
    page3 = (await client.get(f"{ADMIN}?limit=2&before_id={page2['next_before_id']}", headers=admin_headers)).json()
    seen = [i["id"] for p in (page1, page2, page3) for i in p["items"]]
    assert sorted(seen) == sorted(i["id"] for i in items) and len(set(seen)) == 5 and page3["next_before_id"] is None
    only = (await client.get(f"{ADMIN}?status=rejected", headers=admin_headers)).json()["items"]
    assert [i["id"] for i in only] == [items[0]["id"]]
    assert (await client.get(f"{ADMIN}?status=bogus", headers=admin_headers)).status_code == 422
    assert (await client.get(f"{ADMIN}?before_id=nope", headers=admin_headers)).status_code == 422
    assert (await client.get(f"{ADMIN}?limit=101", headers=admin_headers)).status_code == 422


# ------------------------------------------------------------------------------------------ audit, secrets, logs, rollback
async def test_audit_rows_exist_and_hold_no_secrets(client, session_maker, admin_headers, mails):
    ref, status_token, rid, act = await approved(client, admin_headers, mails)
    await client.post(f"{URL}/activate", json={"token": "x" * 43, "password": GOOD_PASSWORD})
    await client.post(f"{URL}/activate", json={"token": act, "password": GOOD_PASSWORD})
    actions = {a.action for a in await audit_rows(session_maker)} & ACCESS_ACTIONS
    assert actions == {
        "access_request_created",
        "access_request_approved",
        "access_request_activated",
        "access_request_activation_failed",
    }
    blob = " ".join(
        f"{a.action} {a.details} {a.username} {a.resource_id} {a.client_ip}" for a in await audit_rows(session_maker)
    )
    for secret in (status_token, act, GOOD_PASSWORD, "ada@example.com", "127.0.0.1"):
        assert secret not in blob, secret
    created = (await audit_rows(session_maker, "access_request_created"))[0]
    assert created.resource_type == "access_request" and created.resource_id == rid and created.details == {"ref": ref}
    assert created.client_ip is None and created.outcome == "success"
    approved_row = (await audit_rows(session_maker, "access_request_approved"))[0]
    assert approved_row.username == "admin1" and approved_row.details["ref"] == ref
    assert not ACCESS_ACTIONS & set(audit_service.EVENT_MODES)  # EVENT_MODES is pinned by another test


async def test_no_token_or_password_reaches_the_logs(client, admin_headers, mails, caplog):
    caplog.set_level(logging.DEBUG)  # includes SQLAlchemy's parameter echo: raw tokens/passwords must still be absent
    body = (await submit(client)).json()
    await client.get(f"{URL}/{body['ref']}/status", headers=status_headers(body["status_token"]))
    listing = await client.get(ADMIN, headers=admin_headers)
    rid = listing.json()["items"][0]["id"]
    await client.post(f"{ADMIN}/{rid}/approve", headers=admin_headers, json={})
    act = token_from(mails)
    await client.post(f"{URL}/activate", json={"token": act, "password": GOOD_PASSWORD})
    await client.post(f"{URL}/activate", json={"token": act, "password": GOOD_PASSWORD})
    text_ = "\n".join(r.getMessage() for r in caplog.records)
    assert text_  # something was logged
    for secret in (body["status_token"], act, GOOD_PASSWORD):
        assert secret not in text_, "a secret reached the log"
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith(("api.", "src.access", "httpx")))
    for digest in (tokens.hash_token(act), tokens.hash_token(body["status_token"])):
        assert digest not in ours  # the application's own logs never carry the stored hashes either


async def test_a_failed_audit_write_rolls_the_whole_decision_back_and_sends_nothing(
    client, session_maker, admin_headers, mails, monkeypatch
):
    await submit(client)
    (row,) = await rows(session_maker)
    before = len(mails)

    async def boom(*_a, **_k):
        raise audit_service.AuditWriteError("down")

    monkeypatch.setattr(audit_service, "log_action", boom)
    r = await client.post(f"{ADMIN}/{row.id}/approve", headers=admin_headers, json={})
    assert r.status_code == 500
    (row,) = await rows(session_maker)
    assert row.status == "pending" and row.activation_token_hash is None and row.decided_by is None
    assert len(mails) == before


async def test_a_failed_account_insert_rolls_activation_back(client, session_maker, admin_headers, mails, monkeypatch):
    _ref, _tok, rid, act = await approved(client, admin_headers, mails)

    class Boom(Exception):
        pass

    original = service.AccessRequest

    async def bad_log(*_a, **_k):
        raise audit_service.AuditWriteError("down")

    monkeypatch.setattr(audit_service, "log_action", bad_log)  # fails AFTER the user and the state change were flushed
    r = await client.post(f"{URL}/activate", json={"token": act, "password": GOOD_PASSWORD})
    assert r.status_code == 500
    monkeypatch.undo()
    (row,) = await rows(session_maker, AccessRequest.id == rid)
    assert row.status == "approved" and row.user_id is None and row.activation_consumed_at is None
    async with session_maker() as s:
        assert (await s.execute(select(User).where(User.username == "ada@example.com"))).first() is None
    assert original is service.AccessRequest and Boom  # silence unused names
    monkeypatch.setenv("ACCESS_TOKEN_PEPPER", "test-pepper-0123456789abcdef-0123456789abcdef")
    assert (await client.post(f"{URL}/activate", json={"token": act, "password": GOOD_PASSWORD})).status_code == 200


# ------------------------------------------------------------------------------------------ mail
async def test_without_a_mail_adapter_the_request_still_works_and_says_so(
    client, session_maker, admin_headers, monkeypatch
):
    monkeypatch.setitem(sys.modules, "src.notify", None)  # `from src.notify import mail` -> ImportError
    body = (await submit(client)).json()
    assert (
        await client.get(f"{URL}/{body['ref']}/status", headers=status_headers(body["status_token"]))
    ).status_code == 200
    (row,) = await rows(session_maker)
    assert (row.notify_state, row.notify_last_code, row.notify_attempts) == ("not_configured", "mail_unavailable", 1)
    assert (await audit_rows(session_maker, "access_request_notify_failed")) == []


async def test_a_failing_mailer_is_recorded_by_code_only(client, session_maker, monkeypatch):
    import types

    async def send(kind, to, ctx):
        raise RuntimeError("smtp password hunter2 rejected")

    fake_pkg = types.ModuleType("src.notify")
    fake_mail = types.ModuleType("src.notify.mail")
    fake_mail.send_access_mail = send
    fake_pkg.mail = fake_mail
    monkeypatch.setitem(sys.modules, "src.notify", fake_pkg)
    monkeypatch.setitem(sys.modules, "src.notify.mail", fake_mail)
    resp = await submit(client)
    assert resp.status_code == 202  # a broken mailer never breaks the request
    (row,) = await rows(session_maker)
    assert (row.notify_state, row.notify_last_code) == ("failed", "error")
    (audit,) = await audit_rows(session_maker, "access_request_notify_failed")
    assert audit.outcome == "failure" and audit.details == {
        "ref": row.ref,
        "kind": "owner_new_request",
        "code": "error",
    }
    assert "hunter2" not in str(vars(row)) and "hunter2" not in str(audit.details)


async def test_mail_is_sent_after_the_response_not_on_the_request_path(client, session_maker, monkeypatch):
    import asyncio

    order: list[str] = []
    started = asyncio.Event()

    async def slow(kind, to, ctx):
        started.set()
        await asyncio.sleep(0.2)
        order.append("mail done")
        return service.DeliveryResult(True, "ok")

    monkeypatch.setattr(service, "deliver", slow)
    resp = await submit(client)
    order.append("response seen")
    assert resp.status_code == 202
    # ASGITransport waits for background tasks before returning, so the mail finished; what matters is that the
    # handler did not await it: the request transaction was committed and the row readable before the mail ran.
    assert started.is_set() and (await rows(session_maker))[0].notify_state == "sent"


# ------------------------------------------------------------------------------------------ switches and setup
async def test_the_feature_flag_turns_every_route_into_a_404(client, admin_headers, monkeypatch):
    monkeypatch.setenv("ACCESS_REQUESTS_ENABLED", "false")
    assert (await submit(client)).status_code == 404
    assert (await client.get(f"{URL}/ZZZZZZZZZZZZ/status")).status_code == 404
    assert (await client.post(f"{URL}/activate", json={})).status_code == 404
    assert (await client.get(ADMIN, headers=admin_headers)).status_code == 404


def test_setup_fails_closed_in_production_without_a_pepper(monkeypatch):
    from api.plugins import access_requests

    monkeypatch.delenv("ACCESS_TOKEN_PEPPER", raising=False)
    monkeypatch.delenv("ACCESS_TOKEN_PEPPER_FILE", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(tokens.PepperMissing):
        access_requests.setup(None)
    monkeypatch.setenv("ENVIRONMENT", "development")
    access_requests.setup(None)  # a development default is allowed (with a warning)
    monkeypatch.setenv("ACCESS_TOKEN_PEPPER", "a-real-pepper-value-0123456789")
    monkeypatch.setenv("ENVIRONMENT", "production")
    access_requests.setup(None)


def test_the_pepper_can_come_from_a_file(monkeypatch, tmp_path):
    secret = tmp_path / "pepper"
    secret.write_text("file-pepper-value-0123456789\n")
    monkeypatch.delenv("ACCESS_TOKEN_PEPPER", raising=False)
    monkeypatch.setenv("ACCESS_TOKEN_PEPPER_FILE", str(secret))
    assert tokens.pepper() == b"file-pepper-value-0123456789"


def test_the_plugin_is_registered_with_the_app():
    from api.main import app
    from api.plugins import _route_keys

    keys = _route_keys(app.routes)
    for key in [
        ("/api/access-requests", "POST"),
        ("/api/access-requests/{ref}/status", "GET"),
        ("/api/access-requests/resend-activation", "POST"),
        ("/api/access-requests/activate", "POST"),
        ("/api/admin/access-requests", "GET"),
        ("/api/admin/access-requests/{request_id}", "GET"),
        ("/api/admin/access-requests/{request_id}/approve", "POST"),
        ("/api/admin/access-requests/{request_id}/reject", "POST"),
        ("/api/admin/access-requests/{request_id}/resend-notification", "POST"),
        ("/api/admin/access-requests/{request_id}/resend-activation", "POST"),
    ]:
        assert key in keys, key


# ------------------------------------------------------------------------------------------ pure units
def test_token_hashing_is_keyed_and_constant_time_shaped(monkeypatch):
    t = tokens.new_token()
    assert len(t) == 43 and t != tokens.new_token()
    h = tokens.hash_token(t)
    assert len(h) == 64 and h == tokens.hash_token(t)
    assert tokens.tokens_match(t, h) and not tokens.tokens_match(t[:-1] + "x", h)
    assert not tokens.tokens_match("", h) and not tokens.tokens_match(t, None) and not tokens.tokens_match(None, h)  # type: ignore[arg-type]
    monkeypatch.setenv("ACCESS_TOKEN_PEPPER", "a-different-pepper-0123456789abcdef")
    assert tokens.hash_token(t) != h  # the pepper is part of the hash


def test_rules_normalise_and_reject():
    assert rules.normalise_email("  A@B.Co ") == "a@b.co"
    for bad in ("", "a", "a@b", "a@@b.co", "a@b.co\x00", "x" * 60 + "@b.co", None, 5):
        with pytest.raises(rules.InvalidRequest):
            rules.normalise_email(bad)
    assert rules.password_problem("x" * 12) is None and rules.password_problem("x" * 128) is None
    assert (
        rules.password_problem("x" * 129) == "length"
        and rules.password_problem("A@B.CO".ljust(12, "x"), "a@b.co") is None
    )
    assert rules.password_problem("ada@example.com", "ada@example.com") == "equals_email"
    assert (
        rules.safe_code("timeout") == "timeout"
        and rules.safe_code("Bad Text!") == "error"
        and rules.safe_code("x" * 30) == "error"
    )
