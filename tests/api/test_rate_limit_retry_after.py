"""Task 5: a slowapi 429 (``@limiter.limit`` routes) carries ``Retry-After`` like every http_limit 429."""

from types import SimpleNamespace

import pytest

from api import errors


def _exc(expiry_seconds):
    item = SimpleNamespace(get_expiry=lambda: expiry_seconds)
    return SimpleNamespace(limit=SimpleNamespace(limit=item), detail="2 per 1 minute")


@pytest.mark.parametrize(("expiry", "expected"), [(60, "60"), (3600, "3600"), (0, "1")])
def test_retry_after_is_the_window_of_the_limit(expiry, expected):
    assert errors._slowapi_retry_after(_exc(expiry)) == expected


@pytest.mark.parametrize("exc", [SimpleNamespace(), SimpleNamespace(limit=None), Exception("x")])
def test_no_header_when_the_exception_carries_no_limit(exc):
    assert errors._slowapi_retry_after(exc) is None


async def test_the_handler_sets_the_header_and_keeps_the_problem_body():
    request = SimpleNamespace(scope={"path": "/x", "type": "http", "headers": []})
    response = await errors.rate_limit_exceeded_handler(request, _exc(60))
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert b"Rate limit exceeded" in response.body
