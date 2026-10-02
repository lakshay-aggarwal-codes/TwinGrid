from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque

from fastapi import APIRouter, Query, WebSocket

from api.auth import decode_token
from api.config import load_ws_limits, normalize_origin
from api.services.live_broadcast_service import ConnectionLimitExceeded, manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["live"])

# -----------------------------------------------------------------------------
# Close codes (application range 4000-4999, plus the standard 1009)
#
# 4001 is the pre-existing "invalid/missing token" code and is sent BEFORE the
# handshake completes. Browsers cannot read a close code on a rejected
# handshake (they see a plain failed connection), so a client should treat
# "failed to open" as "refresh the access token and retry with backoff". The
# codes below that are sent on an ACCEPTED socket are visible to the client.
# -----------------------------------------------------------------------------
WS_CLOSE_INVALID_TOKEN = 4001  # handshake rejected: bad/expired/missing token
WS_CLOSE_TOKEN_EXPIRED = 4002  # accepted socket: access token expired mid-session -> refresh + reconnect
WS_CLOSE_CONNECTION_LIMIT = 4003  # accepted socket: per-user or global cap reached
WS_CLOSE_ORIGIN_NOT_ALLOWED = 4004  # handshake rejected: Origin not in WS_ALLOWED_ORIGINS
WS_CLOSE_RATE_LIMIT = 4005  # accepted socket: too many inbound messages
WS_CLOSE_MESSAGE_TOO_BIG = 1009  # accepted socket: inbound message over WS_MAX_MESSAGE_BYTES

_RATE_WINDOW_SECONDS = 60.0


# -----------------------------------------------------------------------------
# Log redaction (accepted risk R-1 / D-6: the access token travels in the query
# string, and ASGI servers log the request path including it).
# -----------------------------------------------------------------------------
_TOKEN_QS = re.compile(r"""(?i)([?&]token=)[^&\s"']+""")
REDACTED = "[REDACTED]"


def redact_token(text: str) -> str:
    return _TOKEN_QS.sub(rf"\1{REDACTED}", text)


class TokenRedactionFilter(logging.Filter):
    """Rewrites ``token=<value>`` in a log record's message and arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_token(record.msg)
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(redact_token(a) if isinstance(a, str) else a for a in args)
        elif isinstance(args, dict):
            record.args = {k: redact_token(v) if isinstance(v, str) else v for k, v in args.items()}
        return True


# Loggers that print the request target for a WebSocket handshake. A logger-level
# filter only sees records logged directly on that logger, so list them explicitly.
_REDACTED_LOGGERS = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "websockets",
    "websockets.server",
    "wsproto",
)


def install_token_redaction() -> None:
    """Idempotent: attach TokenRedactionFilter to the server loggers above."""
    for name in _REDACTED_LOGGERS:
        target = logging.getLogger(name)
        if not any(isinstance(f, TokenRedactionFilter) for f in target.filters):
            target.addFilter(TokenRedactionFilter())


install_token_redaction()


def origin_allowed(origin: str | None, allowed: tuple[str, ...]) -> bool:
    """True if no allowlist is configured, or ``origin`` is on it.

    A request WITHOUT an Origin header is allowed: browsers always send Origin on
    a WebSocket handshake (that is what makes cross-site hijacking detectable), so
    a missing header means a non-browser client, which this check is not meant to
    stop. The literal Origin ``null`` is never on the list and is rejected.
    """
    if not allowed:
        return True
    if origin is None:
        return True
    return normalize_origin(origin) in allowed


@router.websocket("/ws/live")
async def websocket_live(websocket: WebSocket, token: str = Query(..., alias="token")):
    """Live state updates, broadcast from ONE shared simulation loop (see
    api/services/live_broadcast_service.py) to every connected client --
    not one independent loop per connection. Requires JWT:
    /ws/live?token=<access_token>.

    Session controls (limits from api/config.py ``load_ws_limits``):
    * Origin allowlist (WS_ALLOWED_ORIGINS), checked before the handshake.
    * The access token is checked at connect AND its ``exp`` is enforced for the
      life of the socket: at expiry the server closes with 4002 and the client is
      expected to refresh its token and reconnect.
    * Per-user and global connection caps (4003).
    * Inbound messages are not used by this endpoint, so they are capped in size
      (1009) and rate (4005).
    """
    limits = load_ws_limits()

    if not origin_allowed(websocket.headers.get("origin"), limits.allowed_origins):
        await websocket.close(code=WS_CLOSE_ORIGIN_NOT_ALLOWED)
        return

    try:
        payload = decode_token(token)
        user_id = str(payload["sub"])
        expires_at = float(payload["exp"])
    except Exception:
        await websocket.close(code=WS_CLOSE_INVALID_TOKEN)
        return

    await websocket.accept()
    try:
        manager.connect(
            websocket,
            user_id,
            max_per_user=limits.max_connections_per_user,
            max_global=limits.max_connections_global,
        )
    except ConnectionLimitExceeded as exc:
        logger.warning("WebSocket rejected: %s connection limit reached (user=%s)", exc.scope, user_id)
        await websocket.close(code=WS_CLOSE_CONNECTION_LIMIT, reason=f"connection_limit_{exc.scope}")
        return

    recent: deque[float] = deque()  # monotonic arrival times of inbound messages, last minute
    try:
        while True:
            remaining = expires_at - time.time()
            if remaining <= 0:
                await websocket.close(code=WS_CLOSE_TOKEN_EXPIRED, reason="token_expired")
                break
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=remaining)
            except asyncio.TimeoutError:
                await websocket.close(code=WS_CLOSE_TOKEN_EXPIRED, reason="token_expired")
                break
            if message["type"] == "websocket.disconnect":
                break

            data = message.get("text")
            if data is not None:
                size = len(data.encode("utf-8"))
            else:
                size = len(message.get("bytes") or b"")
            if size > limits.max_message_bytes:
                await websocket.close(code=WS_CLOSE_MESSAGE_TOO_BIG, reason="message_too_big")
                break

            now = time.monotonic()
            recent.append(now)
            while recent and now - recent[0] > _RATE_WINDOW_SECONDS:
                recent.popleft()
            if len(recent) > limits.max_messages_per_minute:
                await websocket.close(code=WS_CLOSE_RATE_LIMIT, reason="rate_limit")
                break
    except Exception as e:
        logger.exception("WebSocket error: %s", e)
    finally:
        manager.disconnect(websocket)
