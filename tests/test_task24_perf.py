"""Task 24: ETag middleware, response cache, pagination guard, carbon-load memo. No FastAPI, Redis or DB needed."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from src import carbon_provider as cp
from src.perf.cache import ResponseCache
from src.perf.etag import ETagMiddleware, compute_etag, if_none_match_matches
from src.perf.pagination import find_unbounded_limits

# ----------------------------------------------------------------------------- ETag


def _run(app, *, path="/api/scenarios", method="GET", headers=()):
    raw = [(k.lower().encode(), v.encode()) for k, v in headers]
    scope = {"type": "http", "method": method, "path": path, "headers": raw}
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    start = sent[0]
    body = b"".join(m.get("body", b"") for m in sent[1:])
    return start["status"], {k.decode(): v.decode() for k, v in start["headers"]}, body


def _app(body=b'{"a":1}', status=200, chunks=None, extra=()):
    async def inner(scope, receive, send):
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), *extra]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        parts = chunks or [body]
        for i, part in enumerate(parts):
            await send({"type": "http.response.body", "body": part, "more_body": i < len(parts) - 1})

    return inner


def test_etag_is_weak_and_deterministic():
    assert compute_etag(b"x") == compute_etag(b"x") != compute_etag(b"y")
    assert compute_etag(b"x").startswith('W/"')


@pytest.mark.parametrize(
    "header,expected",
    [
        (None, False),
        ("", False),
        ("*", True),
        ('"other"', False),
        ('W/"{tag}"', True),
        ('"{tag}"', True),  # weak comparison: strong form of the same tag matches
        ('"zzz", W/"{tag}"', True),
        ('"zzz","yyy"', False),
    ],
)
def test_if_none_match_matching(header, expected):
    etag = compute_etag(b"body")
    tag = etag[3:-1]
    assert if_none_match_matches(header.replace("{tag}", tag) if header else header, etag) is expected


def test_first_request_gets_etag_private_cache_control_and_vary():
    status, headers, body = _run(ETagMiddleware(_app()))
    assert status == 200 and body == b'{"a":1}'
    assert headers["etag"] == compute_etag(b'{"a":1}')
    assert headers["cache-control"] == "private, no-cache"
    assert "Authorization" in headers["vary"]
    assert headers["content-length"] == "7"


def test_matching_if_none_match_gives_empty_304_without_body_headers():
    app = ETagMiddleware(_app())
    etag = _run(app)[1]["etag"]
    status, headers, body = _run(app, headers=[("If-None-Match", etag)])
    assert status == 304 and body == b""
    assert headers["etag"] == etag
    assert "content-length" not in headers and "content-type" not in headers


def test_changed_body_is_a_full_200_again():
    old = _run(ETagMiddleware(_app(b'{"a":1}')))[1]["etag"]
    status, _, body = _run(ETagMiddleware(_app(b'{"a":2}')), headers=[("If-None-Match", old)])
    assert status == 200 and body == b'{"a":2}'


def test_existing_cache_control_and_vary_are_kept_and_extended():
    app = ETagMiddleware(_app(extra=[(b"cache-control", b"max-age=5"), (b"vary", b"Accept-Language")]))
    _, headers, _ = _run(app)
    assert headers["cache-control"] == "max-age=5"
    assert headers["vary"] == "Accept-Language, Authorization"


def test_chunked_body_is_assembled_and_hashed_as_a_whole():
    status, headers, body = _run(ETagMiddleware(_app(chunks=[b'{"a":', b"1}"])))
    assert status == 200 and body == b'{"a":1}' and headers["etag"] == compute_etag(b'{"a":1}')


@pytest.mark.parametrize(
    "kwargs",
    [{"path": "/api/other"}, {"method": "POST"}, {"method": "HEAD"}],
)
def test_other_paths_and_methods_are_untouched(kwargs):
    _, headers, body = _run(ETagMiddleware(_app()), **kwargs)
    assert "etag" not in headers and body == b'{"a":1}'


def test_errors_and_responses_that_already_have_an_etag_are_untouched():
    assert "etag" not in _run(ETagMiddleware(_app(status=404)))[1]
    _, headers, _ = _run(ETagMiddleware(_app(extra=[(b"etag", b'"mine"')])))
    assert headers["etag"] == '"mine"'


def test_prefix_path_matches_simulate_hours():
    assert "etag" in _run(ETagMiddleware(_app()), path="/api/simulate/24")[1]


def test_oversized_body_streams_through_unchanged_and_in_order():
    parts = [b"a" * 60, b"b" * 60, b"c" * 10]
    status, headers, body = _run(ETagMiddleware(_app(chunks=parts), max_body=100))
    assert status == 200 and body == b"".join(parts) and "etag" not in headers


# ----------------------------------------------------------------------------- response cache


class FakeBackend:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.fail = False
        self.calls = 0

    def _check(self):
        self.calls += 1
        if self.fail:
            raise ConnectionError("down")

    def mget(self, keys):
        self._check()
        return [self.data.get(k) for k in keys]

    def set(self, key, value, ttl_ms):
        self._check()
        self.data[key] = value
        self.ttls[key] = ttl_ms

    def incr(self, key):
        self._check()
        self.data[key] = str(int(self.data.get(key, "0")) + 1)
        return int(self.data[key])


def test_second_call_is_a_hit_and_compute_runs_once():
    cache, n = ResponseCache(FakeBackend()), []
    compute = lambda: n.append(1) or {"v": 1}  # noqa: E731
    assert cache.get_or_compute("state", ["k"], 2.0, compute) == {"v": 1}
    assert cache.get_or_compute("state", ["k"], 2.0, compute) == {"v": 1}
    assert len(n) == 1 and (cache.stats.hits, cache.stats.misses) == (1, 1)


def test_ttl_is_passed_to_the_backend_in_milliseconds():
    b = FakeBackend()
    ResponseCache(b).get_or_compute("state", ["k"], 2.0, lambda: 1)
    assert list(b.ttls.values()) == [2000]


def test_different_keys_do_not_collide():
    cache = ResponseCache(FakeBackend())
    assert cache.get_or_compute("state", [0.5], 1, lambda: "a") == "a"
    assert cache.get_or_compute("state", [0.6], 1, lambda: "b") == "b"


def test_invalidate_makes_older_entries_unreadable_for_that_namespace_only():
    cache, n = ResponseCache(FakeBackend()), []
    compute = lambda: n.append(1) or len(n)  # noqa: E731
    assert cache.get_or_compute("state", ["k"], 60, compute) == 1
    assert cache.get_or_compute("scenarios", ["k"], 60, compute) == 2
    assert cache.invalidate("state") is True
    assert cache.get_or_compute("state", ["k"], 60, compute) == 3  # recomputed
    assert cache.get_or_compute("scenarios", ["k"], 60, compute) == 2  # untouched
    assert cache.get_or_compute("state", ["k"], 60, compute) == 3  # and the new entry is served


def test_an_invalidation_during_compute_leaves_no_servable_stale_entry():
    b = FakeBackend()
    cache = ResponseCache(b)

    def compute():
        cache.invalidate("state")  # lands after the generation was read, before the store
        return "old"

    assert cache.get_or_compute("state", ["k"], 60, compute) == "old"
    assert cache.get_or_compute("state", ["k"], 60, lambda: "new") == "new"


def test_backend_down_computes_directly_and_never_raises():
    b = FakeBackend()
    b.fail = True
    cache = ResponseCache(b)
    assert cache.get_or_compute("state", ["k"], 1, lambda: 7) == 7
    assert cache.invalidate("state") is False


def test_breaker_stops_calling_a_dead_backend_then_recovers():
    now = [0.0]
    b = FakeBackend()
    b.fail = True
    cache = ResponseCache(b, clock=lambda: now[0], failure_limit=3, pause_s=10)
    for _ in range(3):
        cache.get_or_compute("s", ["k"], 1, lambda: 1)
    calls = b.calls
    for _ in range(5):
        assert cache.get_or_compute("s", ["k"], 1, lambda: 1) == 1
    assert b.calls == calls and cache.stats.bypassed == 5  # paused: backend not touched
    now[0] = 11.0
    b.fail = False
    cache.get_or_compute("s", ["k"], 1, lambda: 1)
    assert b.calls > calls  # tried again after the pause


def test_compute_errors_propagate_and_are_not_cached():
    cache = ResponseCache(FakeBackend())

    def boom():
        raise ValueError("bad input")

    with pytest.raises(ValueError):
        cache.get_or_compute("s", ["k"], 1, boom)
    assert cache.get_or_compute("s", ["k"], 1, lambda: "ok") == "ok"


def test_non_json_values_are_served_but_not_stored():
    b = FakeBackend()
    cache = ResponseCache(b)
    result = cache.get_or_compute("s", ["k"], 1, lambda: {"x": float("nan")})
    assert result["x"] != result["x"]  # NaN comes back as NaN: served, just never written to the cache
    assert not [k for k in b.data if ":v:" in k]


def test_unreadable_entry_is_recomputed_and_overwritten():
    b = FakeBackend()
    cache = ResponseCache(b)
    cache.get_or_compute("s", ["k"], 1, lambda: 1)
    key = next(k for k in b.data if ":v:" in k)
    b.data[key] = "{not json"
    assert cache.get_or_compute("s", ["k"], 1, lambda: 2) == 2
    assert json.loads(b.data[key])["v"] == 2


# ----------------------------------------------------------------------------- pagination guard


def _spec(**params):
    parameters = [{"name": n, "in": "query", "schema": s} for n, s in params.items()]
    return {"paths": {"/api/x": {"get": {"parameters": parameters}}}}


def test_guard_flags_missing_or_too_large_maximum():
    spec = _spec(limit={"type": "integer"})
    assert find_unbounded_limits(spec) == ["GET /api/x ?limit"]
    assert find_unbounded_limits(_spec(limit={"type": "integer", "maximum": 100000})) == ["GET /api/x ?limit"]


def test_guard_accepts_bounded_including_optional_and_ignores_other_params_and_methods():
    assert find_unbounded_limits(_spec(limit={"type": "integer", "maximum": 200})) == []
    assert find_unbounded_limits(_spec(limit={"anyOf": [{"type": "integer", "maximum": 200}, {"type": "null"}]})) == []
    assert find_unbounded_limits(_spec(offset={"type": "integer"}, hours={"type": "integer"})) == []
    post = {"paths": {"/api/x": {"post": {"parameters": [{"name": "limit", "in": "query", "schema": {}}]}}}}
    assert find_unbounded_limits(post) == []


# ----------------------------------------------------------------------------- carbon-load memo


def _csv(path, base=300, n=48):
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = ["timestamp_utc,zone,carbon_intensity_gco2_per_kwh"]
    rows += [f"{(t0 + timedelta(hours=i)).isoformat()},IN-NO,{base + (i % 24)}" for i in range(n)]
    path.write_text("\n".join(rows), encoding="utf-8")


def test_repeat_load_of_an_unchanged_file_is_the_same_object(tmp_path):
    cp.clear_carbon_cache()
    f = tmp_path / "c.csv"
    _csv(f)
    assert cp.load_carbon_signal(path=f) is cp.load_carbon_signal(path=f)


def test_a_same_size_rewrite_is_seen_immediately(tmp_path):
    cp.clear_carbon_cache()
    f = tmp_path / "c.csv"
    _csv(f, base=300)
    before = cp.load_carbon_signal(path=f)
    _csv(f, base=400)  # same length, different content, same mtime tick possible
    after = cp.load_carbon_signal(path=f)
    assert after is not before and after.values[0] == 400.0 and before.values[0] == 300.0


def test_the_sidecar_is_part_of_the_key(tmp_path):
    cp.clear_carbon_cache()
    f = tmp_path / "c.csv"
    _csv(f)
    unknown = cp.load_carbon_signal(path=f)
    f.with_name(cp.CARBON_META_FILENAME).write_text(json.dumps({"semantic": "average"}), encoding="utf-8")
    assert cp.load_carbon_signal(path=f).semantic == "average" != unknown.semantic


def test_memoised_result_equals_a_fresh_uncached_load(tmp_path):
    cp.clear_carbon_cache()
    f = tmp_path / "c.csv"
    _csv(f)
    cached = cp.load_carbon_signal(path=f)
    fresh = cp._load_carbon_signal_uncached(path=f)
    assert cached == fresh
    assert np.array_equal(cached.curve_by_site_local_hour, fresh.curve_by_site_local_hour)


def test_missing_file_still_returns_the_labelled_fallback_and_is_not_cached(tmp_path):
    cp.clear_carbon_cache()
    sig = cp.load_carbon_signal(path=tmp_path / "absent.csv")
    assert sig.is_fallback and not cp._load_cache


def test_diurnal_curve_is_a_copy_so_callers_cannot_corrupt_the_cache(tmp_path, monkeypatch):
    cp.clear_carbon_cache()
    f = tmp_path / "c.csv"
    _csv(f)
    monkeypatch.setattr(cp, "CLEANED_CARBON_PATH", f)
    first, real = cp.load_diurnal_carbon_intensity()
    assert real is True
    expected = first.copy()
    first[:] = -1.0
    second, _ = cp.load_diurnal_carbon_intensity()
    assert np.array_equal(second, expected)


def test_cache_is_bounded(tmp_path):
    cp.clear_carbon_cache()
    for i in range(cp._LOAD_CACHE_MAX + 4):
        f = tmp_path / f"c{i}.csv"
        _csv(f, base=100 + i)
        cp.load_carbon_signal(path=f)
    assert len(cp._load_cache) == cp._LOAD_CACHE_MAX
