"""Real Gmail mail for the local demo: the wiring around the existing mail adapter (no adapter or access code is changed).

The adapter itself is covered by test_notify_mail.py (fake SMTP server), the HTTP workflow by tests/api/test_task22_*.py.
These tests pin what those cannot see: that the shipped compose overlay really carries every setting into the backend
container through a channel that works, that the app password never appears in a committed file or an image, that SMTP is
opt-in only, and that SMTP failures end up as an honest ``failed`` / ``not_configured`` state instead of a silent ``sent``.
Nothing here opens a network connection.
"""

from __future__ import annotations

import asyncio
import re
import smtplib
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from src.access import service
from src.notify import mail, settings

ROOT = Path(__file__).resolve().parents[1]
APP_PASSWORD = "abcd efgh ijkl mnop"  # the way Google displays it: four groups, spaces are not part of it


def _yaml(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _backend_env(doc: dict) -> dict:
    env = doc["services"]["backend"].get("environment") or {}
    return {k: str(v) for k, v in env.items()} if isinstance(env, dict) else {}


# ----------------------------------------------------------------------------- the overlay


def test_overlay_carries_every_gmail_setting_and_keeps_the_password_out_of_the_environment():
    doc = _yaml("docker-compose.mail.yml")
    backend = doc["services"]["backend"]
    env = _backend_env(doc)
    assert env["ACCESS_NOTIFY_BACKEND"] == "smtp"
    assert env["ACCESS_NOTIFY_SMTP_HOST"] == "smtp.gmail.com"
    assert env["ACCESS_NOTIFY_SMTP_PORT"] == "587"
    assert env["ACCESS_NOTIFY_SMTP_TLS"] == "starttls"
    assert env["ACCESS_PUBLIC_BASE_URL"] == "http://localhost:8080"
    # The password is a mounted file read through the existing *_FILE convention, never an environment value.
    assert "ACCESS_NOTIFY_SMTP_PASSWORD" not in env
    assert env["ACCESS_NOTIFY_SMTP_PASSWORD_FILE"] == "/run/secrets/smtp_password"
    assert "smtp_password" in backend["secrets"]
    assert doc["secrets"]["smtp_password"]["file"] == "./secrets/smtp_password.txt"
    # Addresses come from a required, ignored env file that is passed straight to the container (no interpolation).
    assert {"path": ".env.mail", "required": True} in backend["env_file"]
    # Nothing in the file looks like a pasted app password (16 lowercase letters).
    assert not [v for v in env.values() if re.fullmatch(r"[a-z]{16}", v.replace(" ", ""))]


def test_overlay_does_not_touch_the_environment_name_or_other_services():
    doc = _yaml("docker-compose.mail.yml")
    assert set(doc["services"]) == {"backend"}
    assert "ENVIRONMENT" not in _backend_env(doc)


def test_smtp_is_never_enabled_by_the_base_or_demo_compose_files():
    for name in ("docker-compose.yml", "docker-compose.demo.yml"):
        env = _backend_env(_yaml(name))
        assert not [k for k in env if k.startswith("ACCESS_NOTIFY_SMTP_")], name
        assert env.get("ACCESS_NOTIFY_BACKEND", "") in ("", "console", "file", "disabled"), name
    # The e2e stack talks to a local sink, never to Gmail.
    assert "gmail" not in _text("docker-compose.e2e.yml").lower()
    assert "smtp.gmail.com" not in _text("docker-compose.e2e-file.yml")


def test_the_reason_the_overlay_exists_still_holds_env_demo_is_interpolation_only():
    """If the base file ever starts forwarding ACCESS_NOTIFY_* itself, this overlay can be simplified; until then these
    variables reach the backend only through `.env` or an overlay."""
    base = _yaml("docker-compose.yml")["services"]["backend"]
    assert not [k for k in (base.get("environment") or {}) if k.startswith("ACCESS_")]
    assert {"path": ".env", "required": False} in base["env_file"]


# ----------------------------------------------------------------------------- secrets stay out of git and images


def test_dockerignore_keeps_env_files_and_secret_files_out_of_the_image():
    lines = [ln.strip() for ln in _text(".dockerignore").splitlines()]
    assert ".env.*" in lines and "secrets/" in lines
    assert lines.index("!.env.example") > lines.index(
        ".env.*"
    )  # the negation must come after the pattern it re-includes


def test_gitignore_ignores_the_local_mail_files():
    lines = [ln.strip() for ln in _text(".gitignore").splitlines()]
    assert ".env.*" in lines  # covers .env.mail and .env.demo
    assert "secrets/" in lines  # covers secrets/smtp_password.txt


def test_no_app_password_is_committed_anywhere_in_the_mail_files():
    for name in ("docker-compose.mail.yml", "docker-compose.demo.yml", "scripts/demo.ps1", "scripts/mail-setup.ps1"):
        assert not re.search(r"(?<![A-Za-z0-9])[a-z]{4}( [a-z]{4}){3}(?![A-Za-z0-9])", _text(name)), name


# ----------------------------------------------------------------------------- the scripts


def test_demo_script_adds_the_mail_overlay_only_behind_the_withmail_switch():
    text = _text("scripts/demo.ps1")
    assert "[switch]$WithMail" in text
    base_line = next(ln for ln in text.splitlines() if ln.startswith("$compose = @("))
    assert "docker-compose.mail.yml" not in base_line
    guard = text.index("if ($WithMail) {")
    assert text.index("docker-compose.mail.yml", guard) > guard
    assert text.count("-f', 'docker-compose.mail.yml'") == 1


def test_setup_script_reads_the_password_hidden_and_never_prints_or_exports_it():
    text = _text("scripts/mail-setup.ps1")
    assert "-AsSecureString" in text
    assert "ZeroFreeBSTR" in text
    for line in text.splitlines():
        if re.search(r"Write-(Host|Output|Verbose|Warning)|\becho\b", line):
            assert "$plain" not in line and "$secure" not in line, line
    assert "$env:ACCESS_NOTIFY_SMTP_PASSWORD" not in text and "param(" in text
    assert "[string]$Password" not in text  # never accepted as an argument (it would land in shell history)


# ----------------------------------------------------------------------------- the shipped config, parsed by the app


@pytest.fixture
def shipped_env(monkeypatch, tmp_path):
    """Exactly what the backend container sees with the overlay: the overlay's environment + .env.mail + the secret file."""
    for key in list(settings.os.environ):
        if key.startswith("ACCESS_") or key == "ENVIRONMENT":
            monkeypatch.delenv(key, raising=False)
    pw = tmp_path / "smtp_password"
    pw.write_text(APP_PASSWORD, encoding="utf-8")
    env = _backend_env(_yaml("docker-compose.mail.yml"))
    env["ACCESS_NOTIFY_SMTP_PASSWORD_FILE"] = str(pw)  # /run/secrets/... only exists inside the container
    env.update(
        ENVIRONMENT="development",  # docker-compose.demo.yml
        ACCESS_NOTIFY_SMTP_USER="owner@gmail.com",  # .env.mail
        ACCESS_NOTIFY_OWNER_EMAIL="owner@gmail.com",
        ACCESS_NOTIFY_FROM="owner@gmail.com",
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return pw


def test_the_app_reads_the_shipped_configuration_as_a_complete_gmail_setup(shipped_env):
    s = settings.load_settings()
    assert (s.backend, s.smtp_host, s.smtp_port, s.tls) == ("smtp", "smtp.gmail.com", 587, "starttls")
    assert s.owner_email == s.from_addr == s.smtp_user == "owner@gmail.com"
    assert s.public_base_url == "http://localhost:8080" and s.links_allowed
    assert s.smtp_password == APP_PASSWORD.replace(" ", "")
    assert settings.problems(s) == []
    assert service.activation_url("T0KEN") == "http://localhost:8080/activate#token=T0KEN"


def test_the_same_configuration_cannot_send_link_mail_in_production(shipped_env, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert not settings.load_settings().links_allowed
    assert any("https://" in p for p in settings.problems(settings.load_settings()))

    def no_network(*_a, **_k):  # pragma: no cover - failing here means a socket would have been opened
        raise AssertionError("SMTP must not be contacted")

    monkeypatch.setattr(smtplib, "SMTP", no_network)
    result = asyncio.run(
        mail.send_access_mail("activation", "visitor@example.com", {"name": "V", "activation_url": "x"})
    )
    assert (result.ok, result.code, result.backend) == (False, "not_configured", "smtp")


def test_unset_backend_defaults_stay_safe_without_the_overlay(monkeypatch):
    for key in list(settings.os.environ):
        if key.startswith("ACCESS_NOTIFY_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert settings.load_settings().backend == "console"
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert settings.load_settings().backend == "disabled"


# ----------------------------------------------------------------------------- failures and the stored notification state


def test_a_wrong_app_password_is_reported_as_failed_not_sent(shipped_env, monkeypatch):
    def reject(*_a, **_k):
        raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")

    monkeypatch.setattr(mail, "_smtp_send_blocking", reject)
    result = asyncio.run(
        service.deliver("owner_new_request", "owner@gmail.com", {"ref": "R1", "name": "A", "purpose": "p"})
    )
    assert (result.ok, result.code, result.backend) == (False, "auth_failed", "smtp")
    row = SimpleNamespace(notify_state="pending", notify_attempts=0, notify_last_code=None)
    assert service.mark_notify(row, result) == "failed"
    assert (row.notify_state, row.notify_attempts, row.notify_last_code) == ("failed", 1, "auth_failed")


def test_an_unreadable_password_file_is_an_error_result_never_an_exception(shipped_env, monkeypatch, tmp_path):
    monkeypatch.setenv("ACCESS_NOTIFY_SMTP_PASSWORD_FILE", str(tmp_path / "missing"))
    result = asyncio.run(service.deliver("owner_new_request", "owner@gmail.com", {"ref": "R1", "name": "A"}))
    assert result.ok is False and result.code == "error"


@pytest.mark.parametrize(
    ("ok", "code", "state"),
    [
        (True, "ok", "sent"),
        (False, "not_configured", "not_configured"),
        (False, "no_base_url", "not_configured"),
        (False, "auth_failed", "failed"),
        (False, "timeout", "failed"),
        (False, "refused", "failed"),
        (False, "invalid_recipient", "failed"),
    ],
)
def test_notification_state_is_derived_from_the_delivery_result(ok, code, state):
    row = SimpleNamespace(notify_state="pending", notify_attempts=2, notify_last_code=None)
    assert service.mark_notify(row, SimpleNamespace(ok=ok, code=code)) == state
    assert row.notify_attempts == 3
    assert row.notify_last_code == ("ok" if ok else code)
