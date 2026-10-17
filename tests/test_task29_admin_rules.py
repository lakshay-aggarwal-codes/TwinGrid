"""Task 29: the admin console's pure rules, the webhook registry swap, the delivery log and the webhook delivery
service. Deterministic: no network (``requests.post`` and the SSRF validator are replaced), no database."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone

import pytest
import requests

from api.services import webhook_service as WS
from api.services.webhook_security import WebhookURLError
from src import webhook_deliveries as WD
from src import webhook_registry as WR
from src.admin_console import rules as R

SECRET_URL = "https://hooks.example.com/services/T000/B000/SECRETTOKEN123?key=QUERYSECRET"


# ------------------------------------------------------------------------------------------ roles
@pytest.mark.parametrize(
    "role,expected",
    [
        ("admin", True),
        ("operator", False),
        ("viewer", False),
        ("Admin", False),
        ("", False),
        (None, False),
        ("root", False),
    ],
)
def test_only_the_exact_role_admin_administers(role, expected):
    assert R.can_administer(role) is expected


def test_role_change_matrix():
    ok = {"actor_id": 1, "target_id": 2, "current_role": "viewer", "new_role": "operator", "admin_count": 2}
    assert R.check_role_change(**ok) is None
    assert R.check_role_change(**{**ok, "new_role": "admin"}) is None
    assert R.check_role_change(**{**ok, "target_id": 1}) == "own_role"  # not on yourself, even a no-op
    assert R.check_role_change(**{**ok, "new_role": "viewer"}) == "unchanged"
    assert R.check_role_change(**{**ok, "new_role": "root"}) == "invalid_role"
    demote = {**ok, "current_role": "admin", "new_role": "viewer"}
    assert R.check_role_change(**{**demote, "admin_count": 2}) is None
    assert R.check_role_change(**{**demote, "admin_count": 1}) == "last_admin"
    assert R.check_role_change(**{**demote, "admin_count": 0}) == "last_admin"


def test_every_refusal_has_a_message():
    for code in ("invalid_role", "own_role", "unchanged", "last_admin"):
        assert R.ROLE_CHANGE_MESSAGES[code]


# ------------------------------------------------------------------------------------------ audit filters
def test_filters_are_trimmed_empty_is_unset_and_nothing_is_invented():
    f = R.parse_filters(action=" login_failure ", username="  ", resource_type="")
    assert f.action == "login_failure" and f.username is None and f.resource_type is None
    assert f.as_details() == {"action": "login_failure"}
    assert R.parse_filters() == R.AuditFilters()


def test_filter_validation():
    for kw in (
        {"outcome": "great"},
        {"action": "x" * 65},
        {"username": "y" * 65},
        {"before_id": 0},
        {"before_id": -3},
        {"before_id": True},
        {"since": datetime(2026, 1, 2, tzinfo=timezone.utc), "until": datetime(2026, 1, 1, tzinfo=timezone.utc)},
    ):
        with pytest.raises(R.FilterError):
            R.parse_filters(**kw)
    assert R.parse_filters(outcome="denied").outcome == "denied"


def test_naive_times_are_read_as_utc_and_aware_ones_are_converted():
    f = R.parse_filters(
        since=datetime(2026, 1, 1, 12, 0), until=datetime(2026, 1, 1, 15, 0, tzinfo=timezone(timedelta(hours=3)))
    )
    assert f.since == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert f.until == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert f.as_details()["since"] == "2026-01-01T12:00:00+00:00"


# ------------------------------------------------------------------------------------------ export
@pytest.mark.parametrize("raw", ["=cmd|' /C calc'!A0", "+1+1", "-2+3", "@SUM(A1)", "\t=1", "\r=1"])
def test_csv_cells_that_look_like_formulas_are_neutralised(raw):
    safe = R.csv_safe(raw)
    assert safe == "'" + raw and not safe.startswith(("=", "+", "-", "@", "\t", "\r"))


def test_csv_leaves_ordinary_text_alone():
    for raw in ("login_failure", "10.0.0.1", "a=b", "x-y", "", None):
        assert R.csv_safe(raw) == ("" if raw is None else raw)


ROWS = [
    {
        "id": 3,
        "created_at": "2026-01-01T00:00:00+00:00",
        "username": '=HYPERLINK("http://evil","x")',
        "action": "login_failure",
        "outcome": "failure",
        "resource_type": None,
        "resource_id": None,
        "client_ip": "10.0.0.1",
        "request_id": "r1",
        "details": {"reason": 'bad, "quoted"\nline'},
    },
    {
        "id": 2,
        "created_at": "2026-01-01T00:00:01+00:00",
        "username": "alice",
        "action": "webhook_registered",
        "outcome": "success",
        "resource_type": "webhook",
        "resource_id": "abc",
        "client_ip": None,
        "request_id": None,
        "details": None,
    },
]


def test_csv_export_round_trips_and_a_spreadsheet_would_see_no_formula():
    text = R.to_csv(ROWS)
    parsed = list(csv.reader(io.StringIO(text)))
    assert parsed[0] == list(R.EXPORT_COLUMNS)
    assert len(parsed) == 3
    assert parsed[1][2] == '\'=HYPERLINK("http://evil","x")'  # the cell is text, not a formula
    assert json.loads(parsed[1][9]) == {"reason": 'bad, "quoted"\nline'}  # details survive commas, quotes, newlines
    assert parsed[2][1] == "2026-01-01T00:00:01+00:00" and parsed[2][5] == "webhook" and parsed[2][9] == ""
    for row in parsed[1:]:
        for cell in row:
            assert not cell.startswith(("=", "+", "-", "@", "\t", "\r"))


def test_json_export_keeps_every_column_in_order_and_is_stable():
    a, b = R.to_json(ROWS), R.to_json(ROWS)
    assert a == b
    data = json.loads(a)
    assert [set(r) for r in data] == [set(R.EXPORT_COLUMNS)] * 2
    assert data[0]["username"] == '=HYPERLINK("http://evil","x")'  # JSON is not a spreadsheet: values are exact


def test_export_filename_is_utc_and_has_no_path_characters():
    name = R.export_filename(datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone(timedelta(hours=2))), "csv")
    assert name == "audit-log-20260304T030607Z.csv"
    assert "/" not in name and "\\" not in name and '"' not in name


def test_the_export_bound_is_finite():
    assert 0 < R.EXPORT_MAX_ROWS <= 100_000 and 0 < R.AUDIT_PAGE_MAX <= 1000


# ------------------------------------------------------------------------------------------ webhook identity
def test_a_webhook_is_shown_without_its_path_query_or_credentials():
    view = R.webhook_view(SECRET_URL)
    assert set(view) == {"id", "scheme", "host", "port"}
    assert view["scheme"] == "https" and view["host"] == "hooks.example.com" and view["port"] is None
    assert "SECRET" not in json.dumps(view) and "QUERYSECRET" not in json.dumps(view)
    assert R.webhook_view("https://user:pw@h.example.com:8443/p?q=1")["port"] == 8443
    assert "pw" not in json.dumps(R.webhook_view("https://user:pw@h.example.com:8443/p?q=1"))


def test_webhook_id_is_stable_distinct_and_matches_the_audit_fingerprint():
    a, b = R.webhook_id("https://a.example.com/x"), R.webhook_id("https://a.example.com/y")
    assert a == R.webhook_id("https://a.example.com/x") and a != b and len(a) == 16 and a == a.lower()
    import hashlib

    assert a == hashlib.sha256(b"https://a.example.com/x").hexdigest()[:16]  # = audit_service.url_fingerprint


def test_find_webhook():
    urls = ["https://a.example.com/x", SECRET_URL]
    assert R.find_webhook(urls, R.webhook_id(SECRET_URL)) == SECRET_URL
    assert R.find_webhook(urls, "0" * 16) is None and R.find_webhook([], "0" * 16) is None


# ------------------------------------------------------------------------------------------ registry swap
@pytest.fixture(autouse=True)
def _isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(WR, "REGISTRY_PATH", tmp_path / "webhooks.json")
    monkeypatch.setattr(WD, "LOG_PATH", tmp_path / "webhook_deliveries.json")
    yield


def test_replace_swaps_in_place_and_keeps_the_order():
    for u in ("https://a.example.com", "https://b.example.com", "https://c.example.com"):
        WR.register(u)
    assert WR.replace("https://b.example.com", "https://b2.example.com") == [
        "https://a.example.com",
        "https://b2.example.com",
        "https://c.example.com",
    ]
    assert WR.list_subscribers() == ["https://a.example.com", "https://b2.example.com", "https://c.example.com"]


def test_replace_refuses_an_unknown_old_url_and_a_duplicate_new_one():
    WR.register("https://a.example.com")
    WR.register("https://b.example.com")
    with pytest.raises(KeyError):
        WR.replace("https://nope.example.com", "https://x.example.com")
    with pytest.raises(ValueError):
        WR.replace("https://a.example.com", "https://b.example.com")
    with pytest.raises(ValueError):
        WR.replace("https://a.example.com", "https://a.example.com")
    assert WR.list_subscribers() == ["https://a.example.com", "https://b.example.com"]  # nothing changed


# ------------------------------------------------------------------------------------------ delivery log
def test_a_record_holds_no_url_path_payload_or_message():
    rec = WD.make_record("test", SECRET_URL, ok=False, status_code=500, error_kind="http_error", duration_ms=12)
    assert set(rec) == {"at", "kind", "webhook_id", "host", "ok", "status_code", "error_kind", "duration_ms"}
    assert rec["host"] == "hooks.example.com" and rec["webhook_id"] == R.webhook_id(SECRET_URL)
    assert "SECRET" not in json.dumps(rec)


def test_record_validation_and_clamping():
    with pytest.raises(ValueError):
        WD.make_record("weird", "https://a.example.com", ok=True, status_code=200, error_kind=None, duration_ms=1)
    assert (
        WD.make_record("alert", "https://a.example.com", ok=True, status_code=200, error_kind=None, duration_ms=-5)[
            "duration_ms"
        ]
        == 0
    )


def _rec(n, url="https://a.example.com"):
    return WD.make_record("alert", url, ok=True, status_code=200, error_kind=None, duration_ms=n)


def test_recent_is_newest_first_filtered_and_limited():
    for n in range(5):
        WD.record(_rec(n, "https://a.example.com" if n % 2 == 0 else "https://b.example.com"))
    assert [r["duration_ms"] for r in WD.recent(10)] == [4, 3, 2, 1, 0]
    assert [r["duration_ms"] for r in WD.recent(2)] == [4, 3]
    only_b = WD.recent(10, R.webhook_id("https://b.example.com"))
    assert [r["duration_ms"] for r in only_b] == [3, 1]
    assert WD.recent(0) == []


def test_the_log_is_bounded_and_keeps_the_newest(monkeypatch):
    monkeypatch.setattr(WD, "MAX_RECORDS", 3)
    for n in range(7):
        WD.record(_rec(n))
    assert [r["duration_ms"] for r in WD.recent(10)] == [6, 5, 4]


def test_a_corrupt_or_wrong_shaped_log_reads_as_empty_and_recovers():
    WD.LOG_PATH.write_text("{not json")
    assert WD.recent(5) == []
    WD.record(_rec(1))
    assert len(WD.recent(5)) == 1
    WD.LOG_PATH.write_text(json.dumps({"a": 1}))
    assert WD.recent(5) == []


def test_recording_never_raises_even_if_the_file_cannot_be_written(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(WD, "LOG_PATH", blocker / "sub" / "log.json")  # a path under a regular file: unwritable
    WD.record(_rec(1))  # must not raise


# ------------------------------------------------------------------------------------------ delivery service
class _Resp:
    def __init__(self, code):
        self.status_code = code


def _post_returning(code, calls=None):
    def post(url, json=None, timeout=None, allow_redirects=None):
        if calls is not None:
            calls.append({"url": url, "json": json, "timeout": timeout, "allow_redirects": allow_redirects})
        return _Resp(code)

    return post


@pytest.mark.parametrize(
    "code,ok,kind",
    [
        (200, True, None),
        (204, True, None),
        (301, False, "redirect_refused"),
        (404, False, "http_error"),
        (500, False, "http_error"),
    ],
)
def test_deliver_classifies_the_response(monkeypatch, code, ok, kind):
    monkeypatch.setattr(WS, "validate_webhook_url", lambda u: u)
    monkeypatch.setattr(WS.requests, "post", _post_returning(code))
    r = WS.deliver("https://a.example.com/h", {"event": "x"})
    assert (r.ok, r.status_code, r.error_kind) == (ok, code, kind) and r.duration_ms >= 0


def test_deliver_never_follows_redirects_and_uses_the_timeout(monkeypatch):
    calls = []
    monkeypatch.setattr(WS, "validate_webhook_url", lambda u: u)
    monkeypatch.setattr(WS.requests, "post", _post_returning(200, calls))
    WS.deliver("https://a.example.com/h", {"event": "x"})
    assert calls[0]["allow_redirects"] is False and calls[0]["timeout"] == WS.WEBHOOK_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "exc,kind",
    [
        (requests.Timeout("t"), "timeout"),
        (requests.ConnectionError("c"), "connection"),
        (requests.RequestException("r"), "request_error"),
    ],
)
def test_deliver_reports_a_failure_as_a_kind_never_text_and_never_raises(monkeypatch, exc, kind):
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(WS, "validate_webhook_url", lambda u: u)
    monkeypatch.setattr(WS.requests, "post", boom)
    r = WS.deliver("https://a.example.com/h", {})
    assert (r.ok, r.status_code, r.error_kind) == (False, None, kind)


def test_deliver_blocks_a_url_the_validator_refuses_without_sending(monkeypatch):
    def refuse(u):
        raise WebhookURLError("non-public")

    sent = []
    monkeypatch.setattr(WS, "validate_webhook_url", refuse)
    monkeypatch.setattr(WS.requests, "post", _post_returning(200, sent))
    r = WS.deliver("https://10.0.0.1/h", {})
    assert (r.ok, r.error_kind) == (False, "blocked_url") and sent == []


def test_a_real_delivery_is_logged_without_the_url_secret(monkeypatch):
    monkeypatch.setattr(WS, "validate_webhook_url", lambda u: u)
    monkeypatch.setattr(WS.requests, "post", _post_returning(200))
    WS._post_one(SECRET_URL, {"event": "alert", "secret_payload": "PAYLOADSECRET"})
    (rec,) = WD.recent(5)
    assert rec["kind"] == "alert" and rec["ok"] is True and rec["status_code"] == 200
    assert rec["webhook_id"] == R.webhook_id(SECRET_URL) and rec["host"] == "hooks.example.com"
    blob = json.dumps(rec)
    assert "SECRETTOKEN" not in blob and "QUERYSECRET" not in blob and "PAYLOADSECRET" not in blob


def test_a_failed_delivery_is_logged_as_failed(monkeypatch):
    monkeypatch.setattr(WS, "validate_webhook_url", lambda u: u)
    monkeypatch.setattr(WS.requests, "post", _post_returning(503))
    WS._post_one("https://a.example.com/h", {})
    (rec,) = WD.recent(5)
    assert (rec["ok"], rec["status_code"], rec["error_kind"]) == (False, 503, "http_error")


def test_send_test_posts_a_clearly_labelled_test_event_and_logs_it_as_a_test(monkeypatch):
    calls = []
    monkeypatch.setattr(WS, "validate_webhook_url", lambda u: u)
    monkeypatch.setattr(WS.requests, "post", _post_returning(200, calls))
    r = WS.send_test("https://a.example.com/h")
    assert r.ok is True
    payload = calls[0]["json"]
    assert payload["event"] == "test" and payload["origin"] == "admin_console" and "not an alert" in payload["note"]
    assert datetime.fromisoformat(payload["sent_at"]).tzinfo is not None
    (rec,) = WD.recent(5)
    assert rec["kind"] == "test" and rec["ok"] is True


def test_a_failure_to_log_does_not_fail_the_delivery(monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(WD, "LOG_PATH", blocker / "sub" / "log.json")
    monkeypatch.setattr(WS, "validate_webhook_url", lambda u: u)
    monkeypatch.setattr(WS.requests, "post", _post_returning(200))
    WS._post_one("https://a.example.com/h", {})  # must not raise
