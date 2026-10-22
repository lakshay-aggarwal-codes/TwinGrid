"""Task 9 (R1): the viewer workflow over REAL SMTP, and an outage followed by a resend.

``test_task22_viewer_workflow.py`` reads ``.eml`` files written by the ``file`` backend. These tests use the ``smtp``
backend against a throw-away SMTP sink (stdlib sockets in a thread, plain text, AUTH accepted, nothing leaves the
machine), so the production path (``smtplib`` connect, login, send, error classification) is the one exercised. The sink is a test
double for the MAIL SERVER only; the app code, the database and the HTTP layer are the real ones.

Covered: owner and activation mail captured over SMTP; approval still succeeds when the mail server is down (the row says
``failed``, no link is claimed as delivered); after the server is back an admin resend delivers a working link.
"""

from __future__ import annotations

import asyncio
import email
import email.policy
import re
import socketserver
import threading

import pytest
from sqlalchemy import select

from api.main import app
from database import get_db
from models.db_models import AccessRequest, User

PUBLIC = "/api/access-requests"
ADMIN = "/api/admin/access-requests"
BASE_URL = "http://localhost:8080"
VISITOR = "smtp.visitor@example.com"
PASSWORD = "correct horse battery staple"


class _Handler(socketserver.StreamRequestHandler):
    def _say(self, text: str) -> None:
        self.wfile.write(text.encode("ascii") + b"\r\n")
        self.wfile.flush()

    def handle(self) -> None:  # noqa: C901 - a tiny state machine, clearer inline
        sink: _Sink = self.server.sink  # type: ignore[attr-defined]
        self._say("220 sink ESMTP")
        rcpt: list[str] = []
        while True:
            line = self.rfile.readline()
            if not line:
                return
            cmd = line[:4].upper()
            if cmd == b"EHLO":
                self.wfile.write(b"250-sink\r\n250 AUTH PLAIN\r\n")
                self.wfile.flush()
            elif cmd == b"HELO":
                self._say("250 sink")
            elif cmd == b"AUTH":
                self._say("235 2.7.0 ok")
            elif cmd == b"MAIL":
                self._say("250 ok")
            elif cmd == b"RCPT":
                match = re.search(rb"<([^>]*)>", line)
                if match:
                    rcpt.append(match.group(1).decode().lower())
                self._say("250 ok")
            elif cmd == b"DATA":
                self._say("354 go")
                chunks: list[bytes] = []
                while True:
                    chunk = self.rfile.readline()
                    if chunk in (b".\r\n", b""):
                        break
                    chunks.append(chunk[1:] if chunk.startswith(b"..") else chunk)
                sink.mails.append((list(rcpt), b"".join(chunks)))
                rcpt = []
                self._say("250 queued")
            elif cmd in (b"RSET", b"NOOP"):
                self._say("250 ok")
            elif cmd == b"QUIT":
                self._say("221 bye")
                return
            else:
                self._say("502 not implemented")


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _Sink:
    def __init__(self, port: int = 0) -> None:
        self.mails: list[tuple[list[str], bytes]] = []
        self._server = _Server(("127.0.0.1", port), _Handler)
        self._server.sink = self  # type: ignore[attr-defined]
        self.port: int = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def to(self, addr: str) -> list[email.message.EmailMessage]:
        return [
            email.message_from_bytes(raw, policy=email.policy.default)  # type: ignore[misc]
            for rcpts, raw in self.mails
            if addr.lower() in rcpts
        ]


def _link_token(msg: email.message.EmailMessage) -> str:
    body = msg.get_body(preferencelist=("plain",))
    assert body is not None
    match = re.search(re.escape(BASE_URL) + r"/activate#token=([A-Za-z0-9_\-]{43})", body.get_content())
    assert match, "the mail has no link of the form <base>/activate#token=<43 chars>"
    return match.group(1)


@pytest.fixture
def smtp_env(monkeypatch):
    """Point the real mail adapter at a local port; the test chooses whether a sink is listening there."""

    def configure(port: int) -> None:
        monkeypatch.setenv("ACCESS_NOTIFY_BACKEND", "smtp")
        monkeypatch.setenv("ACCESS_NOTIFY_SMTP_HOST", "127.0.0.1")
        monkeypatch.setenv("ACCESS_NOTIFY_SMTP_PORT", str(port))
        monkeypatch.setenv("ACCESS_NOTIFY_SMTP_TLS", "none")
        monkeypatch.setenv("ACCESS_NOTIFY_SMTP_USER", "sink")
        monkeypatch.setenv("ACCESS_NOTIFY_SMTP_PASSWORD", "sink")
        monkeypatch.setenv("ACCESS_NOTIFY_TIMEOUT_S", "3")

    monkeypatch.setenv("ACCESS_TOKEN_PEPPER", "test-pepper-0123456789abcdef-0123456789abcdef")
    monkeypatch.setenv("ACCESS_NOTIFY_OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("ACCESS_NOTIFY_FROM", "twingrid@example.com")
    monkeypatch.setenv("ACCESS_PUBLIC_BASE_URL", BASE_URL)
    for name in ("ACCESS_REQUESTS_ENABLED", "ACCESS_REQUEST_TTL_DAYS", "ACCESS_ACTIVATION_TTL_HOURS"):
        monkeypatch.delenv(name, raising=False)
    return configure


@pytest.fixture
async def admin_headers(make_user):
    _, headers = await make_user("smtp-owner-admin", "admin")
    return headers


async def _submit(client) -> dict:
    resp = await client.post(PUBLIC, json={"name": "Sam Tp", "email": VISITOR, "purpose": "SMTP capture check"})
    assert resp.status_code == 202, resp.text
    return resp.json()


async def _item(client, admin_headers, ref) -> dict:
    resp = await client.get(ADMIN, headers=admin_headers)
    assert resp.status_code == 200, resp.text
    (item,) = [i for i in resp.json()["items"] if i["ref"] == ref]
    return item


async def _wait_for(client, admin_headers, ref, state: str) -> dict:
    """The mail runs as a background task; poll the queue until the row shows ``state`` (bounded, 10 s)."""
    item: dict = {}
    for _ in range(50):
        item = await _item(client, admin_headers, ref)
        if item["notify_state"] == state:
            return item
        await asyncio.sleep(0.2)
    pytest.fail(f"notify_state never became {state!r}; last row: {item}")


async def test_owner_and_activation_mail_are_delivered_over_smtp(client, admin_headers, smtp_env):
    sink = _Sink()
    try:
        smtp_env(sink.port)
        ticket = await _submit(client)

        (owner_mail,) = sink.to("owner@example.com")
        assert ticket["ref"] in owner_mail.get_body(preferencelist=("plain",)).get_content()

        item = await _item(client, admin_headers, ticket["ref"])
        assert (await client.post(f"{ADMIN}/{item['id']}/approve", headers=admin_headers, json={})).status_code == 200
        item = await _wait_for(client, admin_headers, ticket["ref"], "sent")

        (activation,) = sink.to(VISITOR)
        assert activation["To"] == VISITOR and activation["From"] == "twingrid@example.com"
        assert item["notify_attempts"] >= 1

        done = await client.post(f"{PUBLIC}/activate", json={"token": _link_token(activation), "password": PASSWORD})
        assert done.status_code == 200, done.text
        login = await client.post("/auth/login", json={"username": VISITOR, "password": PASSWORD})
        assert login.status_code == 200, login.text
    finally:
        sink.stop()


async def test_a_mail_outage_does_not_block_approval_and_a_resend_delivers(client, admin_headers, smtp_env):
    first = _Sink()
    port = first.port
    first.stop()  # nothing is listening on `port` now: connections are refused
    smtp_env(port)

    ticket = await _submit(client)  # the visitor is accepted even though the owner mail cannot be sent
    item = await _item(client, admin_headers, ticket["ref"])
    approve = await client.post(f"{ADMIN}/{item['id']}/approve", headers=admin_headers, json={})
    assert approve.status_code == 200, approve.text  # the decision stands

    failed = await _wait_for(client, admin_headers, ticket["ref"], "failed")
    assert failed["status"] == "approved"
    status_url = f"{PUBLIC}/{ticket['ref']}/status"
    status = (await client.get(status_url, headers={"X-Request-Token": ticket["status_token"]})).json()
    assert status["status"] == "approved" and status["can_activate"] is True  # the page can still offer a resend

    recovered = _Sink(port)  # the mail server is back on the same port
    try:
        before = failed["notify_attempts"]
        resend = await client.post(f"{ADMIN}/{item['id']}/resend-activation", headers=admin_headers)
        assert resend.status_code == 200, resend.text
        sent = await _wait_for(client, admin_headers, ticket["ref"], "sent")
        assert sent["notify_attempts"] > before

        (activation,) = recovered.to(VISITOR)  # the failed attempt delivered nothing; the resend delivered one mail
        done = await client.post(f"{PUBLIC}/activate", json={"token": _link_token(activation), "password": PASSWORD})
        assert done.status_code == 200, done.text
    finally:
        recovered.stop()


async def test_each_change_is_committed_before_the_response_is_sent(client, admin_headers, session_maker, smtp_env):
    """Regression for the status page answering "not found" right after a submission.

    ``get_db`` normally commits AFTER the response (and background tasks). Here it never commits, so a change survives
    only if the route itself committed before answering; a visitor, the admin queue and sign-in all read straight away.
    """

    async def never_commits():
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = never_commits
    sink = _Sink()
    try:
        smtp_env(sink.port)
        ticket = await _submit(client)
        async with session_maker() as s:
            result = await s.execute(select(AccessRequest).where(AccessRequest.ref == ticket["ref"]))
            row = result.scalar_one_or_none()
        assert row is not None, "the new request was not committed before the 202 was sent"
        status_url = f"{PUBLIC}/{ticket['ref']}/status"
        assert (await client.get(status_url, headers={"X-Request-Token": ticket["status_token"]})).status_code == 200

        assert (await client.post(f"{ADMIN}/{row.id}/approve", headers=admin_headers, json={})).status_code == 200
        async with session_maker() as s:
            assert (await s.get(AccessRequest, row.id)).status == "approved", "approval was not committed"

        await _wait_for(client, admin_headers, ticket["ref"], "sent")
        token = _link_token(sink.to(VISITOR)[0])
        done = await client.post(f"{PUBLIC}/activate", json={"token": token, "password": PASSWORD})
        assert done.status_code == 200, done.text
        async with session_maker() as s:
            found = await s.execute(select(User).where(User.username == VISITOR))
            assert found.scalar_one_or_none() is not None, "activation was not committed"
    finally:
        sink.stop()
