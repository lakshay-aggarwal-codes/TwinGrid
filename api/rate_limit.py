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

import asyncio
import functools
import logging
import math
import re
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from fastapi import HTTPException, Request, status
from slowapi import Limiter

from api import config
from api.errors import ApiError

T = TypeVar("T")

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
        route = request.scope.get("route")
        if getattr(route, "path", request.url.path) in config.HTTP_LIMIT_EXEMPT_PATHS:
            return  # infrastructure probes (/livez, /healthz) are never limited
        cap = config.max_query_string_chars()
        if len(request.url.query) > cap:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Query string too large (max {cap} characters)",
            )
        if not limiter.enabled or not config.http_limits_enabled():  # HTTP_LIMITS_ENABLED=false is the rollback switch
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


# -----------------------------------------------------------------------------
# Compute guard (T14): bounded concurrency + wall-clock timeout for compute-heavy routes
# -----------------------------------------------------------------------------
#
# At most MAX_CONCURRENT_COMPUTE compute-heavy requests run per process; the next one gets 429 (Retry-After: 1)
# instead of queueing, so the thread pool and memory cannot be filled by a burst. A request that runs longer than
# COMPUTE_TIMEOUT_S gets 504.
#
# Python cannot cancel a running thread. Therefore:
# * ``run_compute`` (plain functions, run in a worker thread): the slot is held until the thread REALLY finishes,
#   even after the client has been answered with 504, so the bound on concurrently running compute stays true.
# * ``run_compute_async`` (coroutines, e.g. POST /api/optimize whose rollout runs in ``asyncio.to_thread``): the
#   coroutine is cancelled on timeout and the slot is released then, but a worker thread it already started
#   (bounded: hours <= 168) may keep running to completion in the background. Recorded in T14_evidence.md.
# The counters live in this process only (no cross-worker limit), like the request-rate windows above.

_in_flight = 0


def compute_in_flight() -> int:
    """Number of compute slots currently held (for tests and diagnostics)."""
    return _in_flight


def _reset_compute_guard() -> None:
    """Test helper: forget all held slots."""
    global _in_flight
    _in_flight = 0


def _acquire_slot() -> None:
    global _in_flight
    if _in_flight >= config.max_concurrent_compute():
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "compute_busy",
            "Too many compute-heavy requests are already running. Retry shortly.",
            headers={"Retry-After": "1"},
        )
    _in_flight += 1


def _release_slot(_: object = None) -> None:
    global _in_flight
    _in_flight = max(0, _in_flight - 1)


def _timeout_error(timeout: float) -> ApiError:
    return ApiError(
        status.HTTP_504_GATEWAY_TIMEOUT,
        "compute_timeout",
        f"The request exceeded its compute budget of {timeout:g} seconds.",
    )


def _consume_exception(fut: "asyncio.Future[Any]") -> None:
    """Mark the outcome of an abandoned (timed-out / disconnected) future as retrieved."""
    if not fut.cancelled():
        fut.exception()


async def run_compute(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run blocking ``func`` in a worker thread under the concurrency bound and the timeout (see above)."""
    _acquire_slot()
    loop = asyncio.get_running_loop()
    try:
        fut = loop.run_in_executor(None, functools.partial(func, *args, **kwargs))
    except BaseException:
        _release_slot()
        raise
    fut.add_done_callback(_release_slot)  # slot is freed when the THREAD finishes, not when we stop waiting
    fut.add_done_callback(_consume_exception)
    timeout = config.compute_timeout_s()
    try:
        return await asyncio.wait_for(asyncio.shield(fut), timeout)
    except asyncio.TimeoutError:
        raise _timeout_error(timeout) from None


async def run_compute_async(func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
    """Await coroutine function ``func`` under the concurrency bound and the timeout; cancelled on timeout."""
    _acquire_slot()
    timeout = config.compute_timeout_s()
    try:
        return await asyncio.wait_for(func(*args, **kwargs), timeout)
    except asyncio.TimeoutError:
        raise _timeout_error(timeout) from None
    finally:
        _release_slot()
