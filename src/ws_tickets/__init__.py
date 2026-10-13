"""WebSocket tickets (Task 6): short-lived, single-use, opaque credentials for ``/ws/live?ticket=``.

Why: browsers cannot set headers on a WebSocket handshake, so the access token used to travel in the query
string, where proxies and server logs can capture it. A ticket is exchanged for it over an authenticated
``POST /auth/ws-ticket`` (the access token goes in the ``Authorization`` header) and is worth nothing after one
use or ``WS_TICKET_TTL_SECONDS`` (default 30) -- so a ticket that ends up in a log line is already dead.

Storage: only the SHA-256 of the ticket is stored, as ``ws_ticket:<hash>`` -> ``{"sub", "exp"}``.

* Redis (``REDIS_URL``, the sync client the API already uses elsewhere; calls run in a worker thread). Redeem is
  one MULTI/EXEC ``GET`` + ``DEL``, so two concurrent redeems cannot both succeed.
* In-memory fallback: DEVELOPMENT / TEST ONLY (per process; useless with several workers). In production (or an
  unrecognised ENVIRONMENT) the store refuses to issue without Redis -> ``TicketStoreUnavailable`` -> the endpoint
  answers 503 and the frontend falls back to the token flow.

``exp`` is the access token's own expiry: the socket is closed with 4002 when it passes, exactly as with ``?token=``.

This module reads the environment only; it imports nothing from ``api`` (``api.startup_checks`` uses it).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "TicketStoreUnavailable",
    "issue_ticket",
    "query_token_allowed",
    "redeem_ticket",
    "redis_configured",
    "reset_for_tests",
    "set_redis_factory",
    "ticket_ttl_seconds",
]

DEFAULT_TTL_SECONDS = 30
MAX_TTL_SECONDS = 300
_KEY_PREFIX = "ws_ticket:"
_MEMORY_CAP = 10_000
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class TicketStoreUnavailable(RuntimeError):
    """No usable ticket store (production without Redis, or Redis down in production). Message is client-safe."""


# ----------------------------------------------------------------------------- configuration (read per call)


def ticket_ttl_seconds() -> int:
    """WS_TICKET_TTL_SECONDS: default 30; malformed or <= 0 -> default; capped at 300."""
    raw = os.getenv("WS_TICKET_TTL_SECONDS", "").strip()
    if not raw:
        return DEFAULT_TTL_SECONDS
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        logger.warning("WS_TICKET_TTL_SECONDS is not a positive integer; using %d", DEFAULT_TTL_SECONDS)
        return DEFAULT_TTL_SECONDS
    return min(value, MAX_TTL_SECONDS)


def query_token_allowed() -> bool:
    """WS_ALLOW_QUERY_TOKEN: may ``/ws/live?token=`` still be used? Default TRUE in this task so the live feed can
    never break; an unrecognised value also means true (and says so in the log)."""
    raw = os.getenv("WS_ALLOW_QUERY_TOKEN", "").strip().lower()
    if not raw or raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    logger.warning("WS_ALLOW_QUERY_TOKEN is not a boolean; keeping ?token= enabled")
    return True


def redis_configured() -> bool:
    return bool(os.getenv("REDIS_URL", "").strip())


def _strict_environment() -> bool:
    name = os.getenv("ENVIRONMENT", "development").strip().lower()
    return name == "production" or name not in ("development", "test")


# ----------------------------------------------------------------------------- stores

_lock = threading.Lock()
_memory: dict[str, tuple[float, str]] = {}  # key -> (expires_at epoch, json value)
_redis_factory: Callable[[], Any] | None = None
_redis_client: Any = None


def set_redis_factory(factory: Callable[[], Any] | None) -> None:
    """Test hook: supply the Redis-like client (``set(key, value, ex=)``, ``pipeline()``)."""
    global _redis_factory, _redis_client
    _redis_factory = factory
    _redis_client = None


def reset_for_tests() -> None:
    global _redis_client
    with _lock:
        _memory.clear()
    _redis_client = None


def _client() -> Any:
    global _redis_client
    if _redis_client is None:
        if _redis_factory is not None:
            _redis_client = _redis_factory()
        else:
            from redis import Redis

            _redis_client = Redis.from_url(
                os.environ["REDIS_URL"], socket_connect_timeout=1, socket_timeout=1, decode_responses=True
            )
    return _redis_client


def _key(ticket: str) -> str:
    return _KEY_PREFIX + hashlib.sha256(ticket.encode("utf-8")).hexdigest()


def _memory_put(key: str, value: str, ttl: int) -> None:
    now = time.time()
    with _lock:
        if len(_memory) >= _MEMORY_CAP:
            for stale in [k for k, (exp, _v) in _memory.items() if exp <= now]:
                del _memory[stale]
            if len(_memory) >= _MEMORY_CAP:
                raise TicketStoreUnavailable("Ticket store is full; retry shortly.")
        _memory[key] = (now + ttl, value)


def _memory_take(key: str) -> str | None:
    now = time.time()
    with _lock:
        entry = _memory.pop(key, None)
    if entry is None or entry[0] <= now:
        return None
    return entry[1]


def _use_redis() -> bool:
    return redis_configured() or _redis_factory is not None


def issue_ticket(subject: str, expires_at: float) -> tuple[str, int]:
    """Blocking. Mint a ticket for ``subject`` whose socket session ends at ``expires_at`` (epoch seconds).

    Returns ``(ticket, ttl_seconds)``. Raises TicketStoreUnavailable when no permitted store works.
    """
    ttl = ticket_ttl_seconds()
    ticket = secrets.token_urlsafe(32)
    key = _key(ticket)
    value = json.dumps({"sub": str(subject), "exp": float(expires_at)})
    if _use_redis():
        try:
            _client().set(key, value, ex=ttl)
            return ticket, ttl
        except Exception:  # noqa: BLE001 -- any Redis failure: log without detail, then decide by environment
            logger.warning("ws-ticket: Redis unavailable while issuing")
            if _strict_environment():
                raise TicketStoreUnavailable("Ticket service unavailable.") from None
    elif _strict_environment():
        raise TicketStoreUnavailable("Ticket service unavailable.")
    _memory_put(key, value, ttl)  # development / test only
    return ticket, ttl


def redeem_ticket(ticket: str) -> dict[str, Any] | None:
    """Blocking. Atomically consume ``ticket``; ``{"sub": str, "exp": float}`` or None (unknown, used, expired)."""
    if not ticket or len(ticket) > 256:
        return None
    key = _key(ticket)
    raw: str | None = None
    if _use_redis():
        try:
            pipe = _client().pipeline(transaction=True)
            pipe.get(key)
            pipe.delete(key)
            raw = pipe.execute()[0]
        except Exception:  # noqa: BLE001
            logger.warning("ws-ticket: Redis unavailable while redeeming")
            raw = None
    if raw is None and not _strict_environment():
        raw = _memory_take(key)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        return {"sub": str(data["sub"]), "exp": float(data["exp"])}
    except (ValueError, KeyError, TypeError):
        return None
