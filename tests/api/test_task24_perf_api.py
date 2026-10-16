"""Task 24 at HTTP level: ETag/304, gzip, auth-before-304, the opt-in response cache, the pagination guard."""

import pytest

from api.main import app
from api.plugins import performance
from api.services import twin_service
from src.perf.cache import ResponseCache
from src.perf.pagination import find_unbounded_limits
from tests.test_task24_perf import FakeBackend


async def test_scenarios_get_an_etag_and_a_matching_request_gets_304(client, viewer_headers):
    first = await client.get("/api/scenarios", headers=viewer_headers)
    assert first.status_code == 200
    etag = first.headers["etag"]
    assert etag.startswith('W/"') and "no-cache" in first.headers["cache-control"]
    again = await client.get("/api/scenarios", headers={**viewer_headers, "If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""
    assert again.headers["etag"] == etag
    stale = await client.get("/api/scenarios", headers={**viewer_headers, "If-None-Match": 'W/"something-else"'})
    assert stale.status_code == 200 and stale.json() == first.json()


async def test_a_matching_etag_never_bypasses_authentication(client, viewer_headers):
    etag = (await client.get("/api/scenarios", headers=viewer_headers)).headers["etag"]
    r = await client.get("/api/scenarios", headers={"If-None-Match": etag})  # no token
    assert r.status_code == 401


async def test_large_json_is_gzipped_when_the_client_accepts_it(client, viewer_headers):
    r = await client.get("/api/scenarios", headers={**viewer_headers, "Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers.get("content-encoding") == "gzip"
    assert "scenarios" in r.json()  # httpx decoded it


async def test_state_shape_is_unchanged_by_the_middleware(client, viewer_headers):
    r = await client.get("/api/state", params={"utilisation": 0.6, "outside_temp": 22}, headers=viewer_headers)
    assert r.status_code == 200 and {"timestamp", "pue", "cooling_mode"} <= r.json().keys()
    assert "etag" in r.headers


@pytest.fixture
def fake_cache():
    cache = ResponseCache(FakeBackend())
    performance.install_cache(cache, {"state", "scenarios"})
    yield cache
    performance.uninstall_cache()


async def test_opt_in_cache_serves_the_second_state_request_from_the_cache(client, viewer_headers, fake_cache):
    params = {"utilisation": 0.55, "outside_temp": 21}
    a = await client.get("/api/state", params=params, headers=viewer_headers)
    b = await client.get("/api/state", params=params, headers=viewer_headers)
    assert a.status_code == b.status_code == 200 and a.json() == b.json()  # same preview, same timestamp
    assert fake_cache.stats.hits == 1 and fake_cache.stats.misses == 1
    assert a.headers["etag"] == b.headers["etag"]  # a stable body is what makes a 304 possible
    other = await client.get("/api/state", params={"utilisation": 0.9}, headers=viewer_headers)
    assert other.status_code == 200 and fake_cache.stats.misses == 2


async def test_invalidating_the_namespace_recomputes(client, viewer_headers, fake_cache):
    await client.get("/api/state", headers=viewer_headers)
    fake_cache.invalidate("state")
    await client.get("/api/state", headers=viewer_headers)
    assert fake_cache.stats.hits == 0 and fake_cache.stats.misses == 2


def test_live_twin_calls_are_never_cached(fake_cache):
    out = twin_service.compute_state(0.5, 25.0, 0.0, "auto", live=True)
    assert not isinstance(out["timestamp"], str)  # raw twin output, not the JSON form
    assert fake_cache.stats.hits == fake_cache.stats.misses == 0


async def test_a_dead_cache_backend_does_not_change_the_response(client, viewer_headers):
    backend = FakeBackend()
    backend.fail = True
    performance.install_cache(ResponseCache(backend), {"state"})
    try:
        r = await client.get("/api/state", headers=viewer_headers)
    finally:
        performance.uninstall_cache()
    assert r.status_code == 200 and {"pue", "cooling_mode"} <= r.json().keys()


def test_every_page_size_parameter_in_the_api_has_a_maximum():
    assert find_unbounded_limits(app.openapi(), max_limit=5000) == []
