"""Shared HTTP limits.

Two mechanisms share one ``limiter`` object (so the existing ``limiter.enabled``
switch and ``limiter.reset()`` used by the test-suite cover both):

* slowapi, keyed by client IP -- still used by the /auth/* routes (unchanged).
* ``http_limit(scope)`` -- a FastAPI dependency (T5) giving an in-memory
  sliding-window limit per user (valid bearer token) or, failing that, per
  client IP. Over the limit -> 429 with ``Retry-After``. It also rejects an
  oversized query string with 413 before doing anything else.

In-memory means per process: with several workers/replicas each has its own
counters. That is accepted for the current single-process deployment; no Redis.

Client identity: ``X-Forwarded-For`` is used ONLY when ``TRUST_PROXY_HEADERS`` is
enabled (see api/config.py), and then only the entry added by the nearest
``TRUSTED_PROXY_HOPS`` trusted proxies -- never the spoofable leftmost value.
Enable it only when the app is reachable exclusively through that proxy.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
from collections import deque

from fastapi import HTTPException, Request, status
from slowapi import Limiter

from api import config

logger = logging.getLogger(__name__)

_UNIT_SECONDS = {
    "s": 1,
    "sec": 1,
    "second": 1,
    "m": 60,
    "min": 60,
    "minute": 60,
    "h": 3600,
    "hour": 3600,
    "d": 86400,
    "day": 86400,
}
_RATE_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d*)\s*([a-z]+?)s?\s*$", re.IGNORECASE)


def parse_rate(raw: str) -> tuple[int, int]:
    """``"30/minute"`` -> (30, 60). ``"5/10 seconds"`` -> (5, 10). ValueError if malformed."""
    match = _RATE_RE.match(raw)
    if not match:
        raise ValueError(f"invalid rate limit {raw!r}")
    count, multiple, unit = int(match.group(1)), int(match.group(2) or 1), match.group(3).lower()
    if count < 1 or multiple < 1 or unit not in _UNIT_SECONDS:
        raise ValueError(f"invalid rate limit {raw!r}")
    return count, multiple * _UNIT_SECONDS[unit]


def client_ip(request: Request) -> str:
    """Client identity for rate limiting (see module docstring)."""
    peer = request.client.host if request.client else "unknown"
    if not config.trust_proxy_headers():
        return peer
    header = request.headers.get("x-forwarded-for")
    if not header:
        return peer
    hops = config.trusted_proxy_hops()
    parts = [p.strip() for p in header.split(",") if p.strip()]
    if len(parts) < hops:
        return peer
    return parts[-hops]


class AppLimiter(Limiter):
    """slowapi Limiter whose reset() also clears the in-memory http_limit windows."""

    def reset(self) -> None:  # noqa: D102
        try:
            super().reset()
        finally:
            _reset_windows()


limiter = AppLimiter(key_func=client_ip)


# -----------------------------------------------------------------------------
# In-memory sliding window for http_limit()
# -----------------------------------------------------------------------------

_now = time.monotonic  # indirection so tests can control the clock
_lock = threading.Lock()
_windows: dict[tuple[str, str], deque[float]] = {}
_SWEEP_THRESHOLD = 10_000


def _reset_windows() -> None:
    with _lock:
        _windows.clear()


def _sweep(now: float, horizon: float) -> None:
    for key in [k for k, dq in _windows.items() if not dq or dq[-1] <= now - horizon]:
        del _windows[key]


def _hit(scope: str, identity: str, count: int, window: float) -> int | None:
    """Record a request. Returns None if allowed, else seconds until it would be."""
    now = _now()
    with _lock:
        if len(_windows) > _SWEEP_THRESHOLD:
            _sweep(now, 86400)
        dq = _windows.setdefault((scope, identity), deque())
        while dq and dq[0] <= now - window:
            dq.popleft()
        if len(dq) >= count:
            return max(1, math.ceil(dq[0] + window - now))
        dq.append(now)
        return None


def _identity(request: Request) -> str:
    """``user:<id>`` for a valid bearer token, else ``ip:<client ip>``."""
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        try:
            from api.auth import decode_token  # lazy: api.auth imports this module

            sub = decode_token(auth[7:].strip()).get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:  # invalid/expired token -> the route's own auth will 401
            pass
    return f"ip:{client_ip(request)}"


def http_limit(scope: str):
    """Dependency factory: ``@router.get(..., dependencies=[Depends(http_limit("state"))])``.

    ``scope`` must be a key of ``api.config.RATE_LIMIT_DEFAULTS``; its limit is
    read from the environment on every request.
    """
    if scope not in config.RATE_LIMIT_DEFAULTS:
        raise KeyError(f"unknown rate-limit scope {scope!r}")

    async def _dependency(request: Request) -> None:
        cap = config.max_query_string_chars()
        if len(request.url.query) > cap:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Query string too large (max {cap} characters)",
            )
        if not limiter.enabled:
            return
        raw = config.rate_limit_setting(scope)
        try:
            count, window = parse_rate(raw)
        except ValueError:
            default = config.RATE_LIMIT_DEFAULTS[scope][1]
            logger.warning("Invalid %s=%r; using default %s", config.RATE_LIMIT_DEFAULTS[scope][0], raw, default)
            count, window = parse_rate(default)
        retry_after = _hit(scope, _identity(request), count, window)
        if retry_after is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded ({raw}). Retry in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )

    return _dependency
