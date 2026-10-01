"""T5: configurable HTTP limits (429 + Retry-After), proxy-aware identity, input-size caps.

Most per-route tests send NO credentials: the limit is applied before auth and
keys such requests by client IP, so the first call is a cheap 401/403 and the
next is a 429. That exercises every route's limit without running the twin,
PPO or PDF code.
"""

import pytest
from starlette.requests import Request

from api import config, rate_limit
from api.rate_limit import client_ip, limiter, parse_rate
from api.services import anomaly_service

ENV_NAMES = [env for env, _ in config.RATE_LIMIT_DEFAULTS.values()] + [
    "TRUST_PROXY_HEADERS",
    "TRUSTED_PROXY_HOPS",
    "MAX_QUERY_STRING_CHARS",
]
WEBHOOK_URL = "https://example.com/hook"

# (scope, method, url, json body)
ROUTES = [
    ("state", "GET", "/api/state", None),
    ("whatif", "GET", "/api/whatif", None),
    ("benchmark", "GET", "/api/benchmark", None),
    ("simulate", "GET", "/api/simulate/1", None),
    ("anomaly_score", "GET", "/api/anomaly_score?recent_data=[]", None),
    ("esg_report", "GET", "/api/esg_report", None),
    ("shadow_sample", "POST", "/api/shadow_mode/sample", None),
    ("alert_ack", "POST", "/api/alerts/1/acknowledge", None),
    ("webhook", "POST", f"/api/webhooks?url={WEBHOOK_URL}", None),
    ("webhook", "DELETE", f"/api/webhooks?url={WEBHOOK_URL}", None),
    ("optimize", "POST", "/api/optimize", {}),
    ("train_async", "POST", "/api/optimize/train_async", {}),
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def limits_on(client):
    """Enable limiting (the shared `client` fixture disables it) and reset all counters."""
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.reset()
    limiter.enabled = False


def _send(client, method, url, body=None, headers=None):
    return client.request(method, url, json=body, headers=headers)


# ----------------------------------------------------------------------------- parsing / defaults


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("30/minute", (30, 60)),
        ("5/min", (5, 60)),
        ("6/minutes", (6, 60)),
        ("1/second", (1, 1)),
        ("2/10 seconds", (2, 10)),
    ],
)
def test_parse_rate(raw, expected):
    assert parse_rate(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "0/minute", "5/week", "5/", "-1/minute"])
def test_parse_rate_rejects_malformed(raw):
    with pytest.raises(ValueError):
        parse_rate(raw)


def test_default_limits_match_roadmap_table():
    expected = {
        "state": "30/minute",
        "whatif": "30/minute",
        "benchmark": "30/minute",
        "simulate": "6/minute",
        "anomaly_score": "30/minute",
        "esg_report": "6/minute",
        "shadow_sample": "10/minute",
        "alert_ack": "30/minute",
        "webhook": "30/minute",
        "optimize": "10/minute",
        "train_async": "5/minute",
    }
    assert {scope: config.rate_limit_setting(scope) for scope in expected} == expected


# ----------------------------------------------------------------------------- 429 + Retry-After


@pytest.mark.parametrize(
    ("scope", "method", "url", "body"),
    ROUTES,
    ids=[f"{r[1]} {r[2].split('?')[0]}" for r in ROUTES],
)
async def test_route_returns_429_with_retry_after_after_limit(client, limits_on, monkeypatch, scope, method, url, body):
    env_name, _ = config.RATE_LIMIT_DEFAULTS[scope]
    monkeypatch.setenv(env_name, "1/minute")

    first = await _send(client, method, url, body)
    assert first.status_code != 429  # reaches auth (401/403) -- not limited yet

    second = await _send(client, method, url, body)
    assert second.status_code == 429
    retry_after = second.headers["Retry-After"]
    assert retry_after.isdigit() and 1 <= int(retry_after) <= 60
    assert "Rate limit exceeded" in second.json()["detail"]


async def test_webhook_create_and_delete_share_a_bucket(client, limits_on, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_WEBHOOK", "1/minute")
    assert (await _send(client, "POST", f"/api/webhooks?url={WEBHOOK_URL}")).status_code != 429
    assert (await _send(client, "DELETE", f"/api/webhooks?url={WEBHOOK_URL}")).status_code == 429


async def test_limits_are_per_route(client, limits_on, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_STATE", "1/minute")
    await _send(client, "GET", "/api/state")
    assert (await _send(client, "GET", "/api/state")).status_code == 429
    assert (await _send(client, "GET", "/api/benchmark")).status_code != 429


async def test_limits_are_per_user(client, limits_on, monkeypatch, make_user):
    monkeypatch.setenv("RATE_LIMIT_BENCHMARK", "2/minute")
    _, alice = await make_user("alice", "viewer")
    _, bob = await make_user("bob", "viewer")
    codes_a = [(await client.get("/api/benchmark", headers=alice)).status_code for _ in range(3)]
    assert codes_a == [200, 200, 429]
    assert (await client.get("/api/benchmark", headers=bob)).status_code == 200


async def test_window_expires(client, limits_on, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_BENCHMARK", "1/minute")
    now = [1000.0]
    monkeypatch.setattr(rate_limit, "_now", lambda: now[0])
    await client.get("/api/benchmark")
    blocked = await client.get("/api/benchmark")
    assert blocked.status_code == 429 and blocked.headers["Retry-After"] == "60"
    now[0] += 61
    assert (await client.get("/api/benchmark")).status_code != 429


async def test_env_override_changes_the_limit(client, limits_on, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_BENCHMARK", "3/minute")
    codes = [(await client.get("/api/benchmark")).status_code for _ in range(4)]
    assert 429 not in codes[:3]
    assert codes[3] == 429


async def test_invalid_env_value_falls_back_to_default(client, limits_on, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_BENCHMARK", "garbage")
    codes = [(await client.get("/api/benchmark")).status_code for _ in range(5)]
    assert 429 not in codes  # default is 30/minute


async def test_limiter_disabled_switch_is_honoured(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_BENCHMARK", "1/minute")  # `client` fixture leaves the limiter disabled
    codes = [(await client.get("/api/benchmark")).status_code for _ in range(3)]
    assert 429 not in codes


async def test_reset_clears_http_limit_windows(client, limits_on, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_BENCHMARK", "1/minute")
    await client.get("/api/benchmark")
    assert (await client.get("/api/benchmark")).status_code == 429
    limiter.reset()
    assert (await client.get("/api/benchmark")).status_code != 429


# ----------------------------------------------------------------------------- proxy-aware identity


def _request(xff=None, peer="10.0.0.1"):
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request(
        {"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": headers, "client": (peer, 5555)}
    )


def test_xff_ignored_by_default():
    assert client_ip(_request("1.1.1.1, 2.2.2.2")) == "10.0.0.1"


def test_xff_ignored_when_flag_is_false(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "false")
    assert client_ip(_request("1.1.1.1")) == "10.0.0.1"


def test_xff_used_when_trusted(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    assert client_ip(_request("1.1.1.1")) == "1.1.1.1"


def test_trusted_proxy_hops_picks_from_the_right(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    spoofed = "6.6.6.6, 1.1.1.1, 2.2.2.2"  # leftmost is client-controlled
    assert client_ip(_request(spoofed)) == "2.2.2.2"
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
    assert client_ip(_request(spoofed)) == "1.1.1.1"


def test_xff_shorter_than_hops_or_missing_falls_back_to_peer(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "3")
    assert client_ip(_request("1.1.1.1")) == "10.0.0.1"
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    assert client_ip(_request(None)) == "10.0.0.1"


async def test_trusted_proxy_gives_separate_buckets_per_forwarded_client(client, limits_on, monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    monkeypatch.setenv("RATE_LIMIT_BENCHMARK", "1/minute")
    a, b = {"X-Forwarded-For": "9.9.9.1"}, {"X-Forwarded-For": "9.9.9.2"}
    assert (await client.get("/api/benchmark", headers=a)).status_code != 429
    assert (await client.get("/api/benchmark", headers=a)).status_code == 429
    assert (await client.get("/api/benchmark", headers=b)).status_code != 429  # separate bucket


async def test_untrusted_proxy_header_cannot_dodge_the_limit(client, limits_on, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_BENCHMARK", "1/minute")  # TRUST_PROXY_HEADERS unset
    await client.get("/api/benchmark", headers={"X-Forwarded-For": "9.9.9.1"})
    blocked = await client.get("/api/benchmark", headers={"X-Forwarded-For": "9.9.9.2"})
    assert blocked.status_code == 429


# ----------------------------------------------------------------------------- oversized input


async def test_oversized_recent_data_is_rejected_with_422(client, viewer_headers):
    too_long = "[" + "0" * (config.MAX_RECENT_DATA_CHARS + 1) + "]"
    r = await client.get("/api/anomaly_score", params={"recent_data": too_long}, headers=viewer_headers)
    assert r.status_code == 422


async def test_normal_sized_recent_data_is_accepted(client, viewer_headers, monkeypatch):
    monkeypatch.setattr(
        anomaly_service,
        "score_recent_data",
        lambda _raw: {
            "score": 0.0,
            "threshold": 1.0,
            "alert": False,
            "type": "normal",
            "message": "ok",
            "explanation": None,
        },
    )
    window = "[" + ",".join(["[0.123456789,1.234567891,2.345678912,3.456789123,4.567891234]"] * 12) + "]"
    assert len(window) < config.MAX_RECENT_DATA_CHARS
    r = await client.get("/api/anomaly_score", params={"recent_data": window}, headers=viewer_headers)
    assert r.status_code == 200


@pytest.mark.parametrize(
    "path",
    ["/api/state", "/api/whatif", "/api/benchmark", "/api/esg_report", "/api/anomaly_score"],
)
async def test_oversized_query_string_is_rejected_with_413(client, viewer_headers, monkeypatch, path):
    monkeypatch.setenv("MAX_QUERY_STRING_CHARS", "100")
    r = await client.get(path, params={"padding": "x" * 200}, headers=viewer_headers)
    assert r.status_code == 413


async def test_size_cap_applies_even_when_limiter_is_disabled(client, viewer_headers, monkeypatch):
    assert limiter.enabled is False
    monkeypatch.setenv("MAX_QUERY_STRING_CHARS", "50")
    r = await client.get("/api/benchmark", params={"padding": "x" * 100}, headers=viewer_headers)
    assert r.status_code == 413
