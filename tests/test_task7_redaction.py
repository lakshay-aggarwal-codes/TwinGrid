"""Task 7: log redaction and the browser-error-report parser. Pure logic: no app, no database, no network."""

from __future__ import annotations

import json

import pytest

from src import client_errors as ce
from src.log_redaction import REDACTED, redact, redact_value

# (text, secret that must not survive)
SECRET_CASES = [
    ("GET /ws/live?token=eyJhbGciOiJI.eyJzdWIiOiIx.c2ln&x=1", "eyJhbGciOiJI"),
    ("handshake /ws/live?ticket=TICKETVALUE123 accepted", "TICKETVALUE123"),
    ("POST /x?access_token=ACCESSVALUE1&refresh_token=REFRESHVALUE1", "ACCESSVALUE1"),
    ("POST /x?refresh_token=REFRESHVALUE1", "REFRESHVALUE1"),
    ("POST /api/client-errors?key=INGESTKEY0123456789", "INGESTKEY0123456789"),
    ('{"username": "a", "password": "hunter2-hunter2"}', "hunter2-hunter2"),
    ("login body password=hunter2-hunter2 rejected", "hunter2-hunter2"),
    ("Authorization: Bearer opaque.credential-123", "opaque.credential-123"),
    ("headers={'authorization': 'Token abc123secret'}", "abc123secret"),
    ("sent Bearer abc.def.ghi to upstream", "abc.def.ghi"),
    ('{"refresh_token":"r3fr3sh-value"}', "r3fr3sh-value"),
    ("refresh_token: r3fr3sh-value", "r3fr3sh-value"),
    ("env JWT_SECRET_KEY=supersecretvalue loaded", "supersecretvalue"),
    ("X-Admin-Key: adm1n-key-value", "adm1n-key-value"),
    ("stray jwt eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4 in text", "eyJhbGciOiJIUzI1"),
]


@pytest.mark.parametrize(("text", "secret"), SECRET_CASES)
def test_secrets_are_removed_and_the_marker_is_present(text, secret):
    out = redact(text)
    assert secret not in out
    assert REDACTED in out


@pytest.mark.parametrize(("text", "_secret"), SECRET_CASES)
def test_redaction_is_idempotent(text, _secret):
    once = redact(text)
    assert redact(once) == once


@pytest.mark.parametrize(
    "text",
    [
        "GET /api/state -> 200",
        "POST /auth/login -> 401",
        "WebSocket rejected: connection limit reached (user=7)",
        "telemetry conflict sensor=fac1.it_power_kw stream=live",
        "",
    ],
)
def test_ordinary_log_lines_are_untouched(text):
    assert redact(text) == text


def test_redaction_keeps_the_surrounding_structure():
    out = redact('{"user": "bob", "password": "hunter2-hunter2", "n": 3}')
    assert json.loads(out) == {"user": "bob", "password": REDACTED, "n": 3}


def test_redact_value_walks_nested_values_and_leaves_other_types_alone():
    value = {"a": ["x?token=SECRETTOKEN1", 5, None], "b": ("Bearer abc.def.ghi",), "c": 1.5}
    out = redact_value(value)
    assert "SECRETTOKEN1" not in json.dumps(out) and "abc.def.ghi" not in json.dumps(out)
    assert out["a"][1:] == [5, None] and out["c"] == 1.5


# ---- report parsing: exactly what src/lib/errorReporter.ts sends ----------------------------------------------------

REPORT = {
    "level": "error",
    "source": "WebSocket",
    "message": "connection failed",
    "stack": "Error: x\n    at f (app.js:1:1)",
    "page": "/analytics",
    "timestamp": "2026-10-13T09:00:00.000Z",
}


def _raw(**changes) -> bytes:
    data = {**REPORT, **changes}
    return json.dumps({k: v for k, v in data.items() if v is not ...}).encode()


def test_a_report_in_the_reporters_shape_is_accepted_unchanged():
    assert ce.parse_report(_raw()) == REPORT


def test_the_stack_is_optional_and_unknown_fields_are_dropped():
    out = ce.parse_report(_raw(stack=..., extra="x", user_agent="y"))
    assert "stack" not in out and set(out) == {"level", "source", "message", "page", "timestamp"}


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not json",
        b"\xff\xfe",
        b"[]",
        b'"text"',
        _raw(level="fatal"),
        _raw(level=None),
        _raw(message=""),
        _raw(message=5),
        _raw(source=None),
        _raw(page=["/"]),
        _raw(timestamp=""),
        _raw(stack=5),
    ],
)
def test_malformed_reports_are_rejected(raw):
    with pytest.raises(ce.InvalidReport):
        ce.parse_report(raw)


def test_invalid_report_messages_never_echo_the_input():
    with pytest.raises(ce.InvalidReport) as exc:
        ce.parse_report(_raw(level="SECRET-LEVEL-VALUE"))
    assert "SECRET-LEVEL-VALUE" not in str(exc.value)


def test_secrets_in_every_text_field_are_redacted():
    out = ce.parse_report(
        _raw(
            message="failed ws://h/ws/live?token=SECRETONE12 Bearer abc.def.ghi",
            stack="at x ?ticket=SECRETTWO12\n at y",
            page="/p?token=SECRETTHREE",
            source="src?key=SECRETFOUR1234",
        )
    )
    blob = json.dumps(out)
    for secret in ("SECRETONE12", "abc.def.ghi", "SECRETTWO12", "SECRETTHREE", "SECRETFOUR1234"):
        assert secret not in blob


def test_fields_are_capped_and_control_characters_removed():
    out = ce.parse_report(_raw(message="a" * 900 + "\x00\x1b[31m", stack="s" * 5000, page="/" + "p" * 500))
    assert len(out["message"]) == 500 and len(out["stack"]) == 2000 and len(out["page"]) == 200
    assert "\x00" not in out["message"] and "\x1b" not in out["message"]


def test_newlines_in_a_stack_are_kept_but_other_fields_cannot_forge_a_log_line_after_json_encoding():
    out = ce.parse_report(_raw(message='x"}\n{"level":"CRITICAL"'))
    assert json.loads(json.dumps(out))["message"] == out["message"]  # round-trips as one string value


# ---- settings -------------------------------------------------------------------------------------------------------


def test_max_bytes_default_clamp_and_malformed(monkeypatch):
    monkeypatch.delenv("CLIENT_ERRORS_MAX_BYTES", raising=False)
    assert ce.max_bytes() == 8192
    for raw, expected in (("1000", 1000), ("5", 256), ("99999999", 65536), ("abc", 8192), ("", 8192)):
        monkeypatch.setenv("CLIENT_ERRORS_MAX_BYTES", raw)
        assert ce.max_bytes() == expected


def test_rate_limit_default_and_override(monkeypatch):
    monkeypatch.delenv("CLIENT_ERRORS_RATE_LIMIT", raising=False)
    assert ce.rate_limit() == "20/minute"
    monkeypatch.setenv("CLIENT_ERRORS_RATE_LIMIT", " 5/minute ")
    assert ce.rate_limit() == "5/minute"


def test_report_key_must_be_long_enough_and_is_compared_exactly(monkeypatch):
    monkeypatch.delenv("CLIENT_ERRORS_REPORT_KEY", raising=False)
    assert ce.configured_key() is None and not ce.key_matches("anything")
    monkeypatch.setenv("CLIENT_ERRORS_REPORT_KEY", "short")
    assert ce.configured_key() is None  # too short to be a key: treated as not configured
    monkeypatch.setenv("CLIENT_ERRORS_REPORT_KEY", "k" * 16)
    assert ce.key_matches("k" * 16)
    assert not ce.key_matches("k" * 15) and not ce.key_matches("") and not ce.key_matches(None)


@pytest.mark.parametrize(
    ("env", "prod"),
    [("development", False), ("test", False), ("production", True), ("weird", True), (" PRODUCTION ", True)],
)
def test_unknown_environments_count_as_production(monkeypatch, env, prod):
    monkeypatch.setenv("ENVIRONMENT", env)
    assert ce.is_production() is prod
