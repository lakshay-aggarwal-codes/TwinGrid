"""Task 10: mail adapter. A fake local SMTP server stands in for Gmail; real delivery is verified only by
``python -m src.notify`` with real credentials (see docs/env/T10.md)."""

from __future__ import annotations

import asyncio
import base64
import logging
import socket
import socketserver
import threading
import time

import pytest

from src.notify import mail, settings

TOKEN = "SECRET-ACTIVATION-TOKEN-123"
PASSWORD = "app-password-xyz"
ACTIVATION = {
    "name": "Ada",
    "activation_url": f"https://twin.example/activate#token={TOKEN}",
}
OWNER = {
    "ref": "K7Q2M9XD4TAB",
    "name": "Ada Lovelace",
    "purpose": "Reviewing the project",
}


class _Handler(socketserver.StreamRequestHandler):
    def _send(self, line: str) -> None:
        self.wfile.write((line + "\r\n").encode())
        self.wfile.flush()

    def handle(self) -> None:
        srv = self.server
        if srv.mode == "hang":
            time.sleep(3)
            return
        self._send("220 fake ESMTP")
        data_mode, buf = False, []
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode(errors="replace").rstrip("\r\n")
            if data_mode:
                if line == ".":
                    data_mode = False
                    srv.messages.append("\n".join(buf))
                    self._send("250 queued")
                else:
                    buf.append(line[1:] if line.startswith("..") else line)
                continue
            cmd = line.upper()
            if cmd.startswith(("EHLO", "HELO")):
                self._send("250-fake")
                self._send("250 AUTH PLAIN LOGIN")
            elif cmd.startswith("AUTH PLAIN"):
                _, user, pw = base64.b64decode(line.split()[2]).decode().split("\0")
                if srv.mode == "auth_fail" or (user, pw) != (srv.user, srv.password):
                    self._send("535 5.7.8 Username and Password not accepted")
                else:
                    self._send("235 ok")
            elif cmd.startswith("MAIL FROM"):
                self._send("250 ok")
            elif cmd.startswith("RCPT TO"):
                self._send("550 no such user" if "bad@" in line.lower() else "250 ok")
            elif cmd == "DATA":
                data_mode = True
                self._send("354 go")
            elif cmd == "QUIT":
                self._send("221 bye")
                return
            else:
                self._send("250 ok")


class FakeSMTP(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, mode: str = "ok") -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.mode, self.user, self.password, self.messages = (
            mode,
            "owner@gmail.com",
            PASSWORD,
            [],
        )
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def port(self) -> int:
        return self.server_address[1]


@pytest.fixture
def smtp_env(monkeypatch):
    def apply(port: int, **extra):
        env = {
            "ENVIRONMENT": "development",
            "ACCESS_NOTIFY_BACKEND": "smtp",
            "ACCESS_NOTIFY_SMTP_HOST": "127.0.0.1",
            "ACCESS_NOTIFY_SMTP_PORT": str(port),
            "ACCESS_NOTIFY_SMTP_TLS": "none",
            "ACCESS_NOTIFY_SMTP_USER": "owner@gmail.com",
            "ACCESS_NOTIFY_SMTP_PASSWORD": PASSWORD,
            "ACCESS_NOTIFY_TIMEOUT_S": "0.6",
            "ACCESS_PUBLIC_BASE_URL": "https://twin.example",
        }
        env.update(extra)
        for k, v in env.items():
            monkeypatch.setenv(k, v)

    return apply


@pytest.fixture
def server():
    servers = []

    def make(mode="ok"):
        s = FakeSMTP(mode)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.shutdown()
        s.server_close()


def run(coro):
    return asyncio.run(coro)


def test_smtp_success_delivers_activation_link_and_labels_backend(server, smtp_env):
    srv = server()
    smtp_env(srv.port)
    r = run(mail.send_access_mail("activation", "ada@example.com", ACTIVATION))
    assert r == mail.DeliveryResult(True, "ok", "smtp")
    assert len(srv.messages) == 1 and TOKEN in srv.messages[0]


def test_auth_failure(server, smtp_env):
    srv = server("auth_fail")
    smtp_env(srv.port)
    assert run(mail.send_access_mail("rejected", "ada@example.com", {"name": "Ada"})).code == "auth_failed"


@pytest.mark.skipif(
    __import__("sys").platform == "win32",
    reason="Windows does not reset a closed localhost port at once, so the short SMTP timeout fires first",
)
def test_connection_refused(smtp_env):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    smtp_env(port)
    assert run(mail.send_access_mail("rejected", "ada@example.com", {"name": "Ada"})).code == "refused"


def test_timeout(server, smtp_env):
    srv = server("hang")
    smtp_env(srv.port)
    r = run(mail.send_access_mail("rejected", "ada@example.com", {"name": "Ada"}))
    assert (r.ok, r.code, r.backend) == (False, "timeout", "smtp")


def test_invalid_recipient_rejected_by_server_and_by_header_check(server, smtp_env):
    srv = server()
    smtp_env(srv.port)
    assert run(mail.send_access_mail("rejected", "bad@example.com", {"name": "Ada"})).code == "invalid_recipient"
    r = run(mail.send_access_mail("rejected", "ada@example.com\r\nBcc: evil@example.com", {"name": "Ada"}))
    assert r.code == "invalid_recipient" and srv.messages == []


def test_no_token_or_password_in_logs_on_any_path(server, smtp_env, caplog, tmp_path, monkeypatch):
    caplog.set_level(logging.DEBUG)
    srv = server()
    smtp_env(srv.port)
    run(mail.send_access_mail("activation", "ada@example.com", ACTIVATION))
    srv.mode = "auth_fail"
    run(mail.send_access_mail("activation", "ada@example.com", ACTIVATION))
    monkeypatch.setenv("ACCESS_NOTIFY_BACKEND", "console")
    run(mail.send_access_mail("activation", "ada@example.com", ACTIVATION))
    monkeypatch.setenv("ACCESS_NOTIFY_BACKEND", "file")
    monkeypatch.setenv("ACCESS_NOTIFY_FILE_DIR", str(tmp_path))
    run(mail.send_access_mail("activation", "ada@example.com", ACTIVATION))
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert TOKEN not in logged and PASSWORD not in logged


def test_html_escaping_of_name_and_purpose(tmp_path, monkeypatch):
    monkeypatch.setenv("ACCESS_NOTIFY_BACKEND", "file")
    monkeypatch.setenv("ACCESS_NOTIFY_FILE_DIR", str(tmp_path))
    monkeypatch.setenv("ACCESS_PUBLIC_BASE_URL", "https://twin.example")
    evil = {
        "ref": "R",
        "name": "<script>alert(1)</script>",
        "purpose": "<img src=x onerror=1>",
    }
    assert run(mail.send_access_mail("owner_new_request", "owner@gmail.com", evil)).ok
    raw = next(tmp_path.glob("*.eml")).read_text()
    html_part = raw.split("text/html", 1)[1]
    assert "<script>" not in html_part and "&lt;script&gt;" in html_part and "<img" not in html_part


def test_production_requires_https_base_url(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ACCESS_NOTIFY_BACKEND", "file")
    monkeypatch.setenv("ACCESS_NOTIFY_FILE_DIR", str(tmp_path))
    monkeypatch.setenv("ACCESS_PUBLIC_BASE_URL", "http://twin.example")
    r = run(mail.send_access_mail("activation", "ada@example.com", ACTIVATION))
    assert (r.ok, r.code) == (False, "not_configured") and not list(tmp_path.glob("*.eml"))
    assert any("https://" in p for p in settings.problems(settings.load_settings()))


def test_file_backend_has_link_console_does_not(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("ACCESS_PUBLIC_BASE_URL", "https://twin.example")
    monkeypatch.setenv("ACCESS_NOTIFY_FILE_DIR", str(tmp_path))
    monkeypatch.setenv("ACCESS_NOTIFY_BACKEND", "file")
    r = run(mail.send_access_mail("activation", "ada@example.com", ACTIVATION))
    assert r.backend == "file" and TOKEN in next(tmp_path.glob("*.eml")).read_text()
    monkeypatch.setenv("ACCESS_NOTIFY_BACKEND", "console")
    r = run(mail.send_access_mail("activation", "ada@example.com", ACTIVATION))
    assert r == mail.DeliveryResult(True, "ok", "console")
    assert TOKEN not in "\n".join(x.getMessage() for x in caplog.records)


def test_disabled_backend(monkeypatch):
    monkeypatch.setenv("ACCESS_NOTIFY_BACKEND", "disabled")
    assert run(mail.send_access_mail("rejected", "a@b.co", {"name": "x"})) == mail.DeliveryResult(
        False, "not_configured", "disabled"
    )


def test_owner_mail_links_only_to_admin_page_with_no_decision_link(tmp_path, monkeypatch):
    monkeypatch.setenv("ACCESS_NOTIFY_BACKEND", "file")
    monkeypatch.setenv("ACCESS_NOTIFY_FILE_DIR", str(tmp_path))
    monkeypatch.setenv("ACCESS_PUBLIC_BASE_URL", "https://twin.example")
    assert run(mail.send_access_mail("owner_new_request", "owner@gmail.com", OWNER)).ok
    raw = next(tmp_path.glob("*.eml")).read_text()
    assert "https://twin.example/admin" in raw and "/approve" not in raw and "token" not in raw.lower()


def test_gmail_defaults_and_app_password_spaces(monkeypatch):
    for k in (
        "ACCESS_NOTIFY_SMTP_HOST",
        "ACCESS_NOTIFY_SMTP_PORT",
        "ACCESS_NOTIFY_SMTP_TLS",
        "ACCESS_NOTIFY_OWNER_EMAIL",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ACCESS_NOTIFY_BACKEND", "smtp")
    monkeypatch.setenv("ACCESS_NOTIFY_SMTP_USER", "me@gmail.com")
    monkeypatch.setenv("ACCESS_NOTIFY_SMTP_PASSWORD", "abcd efgh ijkl mnop")
    s = settings.load_settings()
    assert (s.smtp_host, s.smtp_port, s.tls) == ("smtp.gmail.com", 587, "starttls")
    assert s.smtp_password == "abcdefghijklmnop" and s.owner_email == "me@gmail.com" and s.from_addr == "me@gmail.com"


def test_default_backend_by_environment(monkeypatch):
    monkeypatch.delenv("ACCESS_NOTIFY_BACKEND", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert settings.load_settings().backend == "disabled"
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert settings.load_settings().backend == "console"


def test_starttls_runs_before_login(monkeypatch):
    calls: list[str] = []

    class Stub:
        def __init__(self, *a, **k):
            calls.append("connect")

        def ehlo(self):
            calls.append("ehlo")

        def starttls(self, context=None):
            calls.append("starttls")

        def login(self, u, p):
            calls.append("login")

        def send_message(self, m):
            calls.append("send")

        def quit(self):
            calls.append("quit")

    monkeypatch.setattr(mail.smtplib, "SMTP", Stub)
    for k, v in {
        "ACCESS_NOTIFY_BACKEND": "smtp",
        "ACCESS_NOTIFY_SMTP_USER": "me@gmail.com",
        "ACCESS_NOTIFY_SMTP_PASSWORD": "pw",
        "ACCESS_PUBLIC_BASE_URL": "https://twin.example",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("ACCESS_NOTIFY_SMTP_TLS", raising=False)
    assert run(mail.send_access_mail("rejected", "ada@example.com", {"name": "Ada"})).ok
    assert calls.index("starttls") < calls.index("login") < calls.index("send")


def test_results_only_use_contract_codes(server, smtp_env):
    srv = server("auth_fail")
    smtp_env(srv.port)
    r = run(mail.send_access_mail("rejected", "ada@example.com", {"name": "Ada"}))
    assert r.code in mail.CODES and set(vars(r)) == {"ok", "code", "backend"}
