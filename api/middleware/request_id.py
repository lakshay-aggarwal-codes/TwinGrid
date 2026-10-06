"""
Request-ID propagation: every request gets a UUID (or reuses an incoming
X-Request-ID header), available to logging via a ContextVar and echoed
back in the response header -- lets one request be traced across every
log line it produces, and lets a client correlate their request with
server-side logs if they need to report an issue.

T14: an incoming X-Request-ID is accepted ONLY if it matches ``^[A-Za-z0-9._-]{8,64}$``; anything else
(too short/long, spaces, control characters, log-injection attempts) is ignored and a fresh UUID is used.
The id is also stored in ``scope["request_id"]`` so error handlers can put it in the response body.

Pure ASGI (not BaseHTTPMiddleware) so it adds no extra task/buffering layer and also covers WebSockets.
"""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9._-]{8,64}")
HEADER_NAME = "X-Request-ID"
_HEADER_BYTES = HEADER_NAME.lower().encode("latin-1")


def accept_request_id(raw: str | None) -> str | None:
    """``raw`` if it is a valid client-supplied id, else None."""
    if raw is not None and _REQUEST_ID_RE.fullmatch(raw):
        return raw
    return None


def get_request_id(scope: Scope) -> str:
    """The id of the request in ``scope`` (set by RequestIDMiddleware), else the contextvar, else ``-``."""
    return str(scope.get("request_id") or request_id_var.get())


class RequestIDMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        incoming = None
        for name, value in scope.get("headers", []):
            if name == _HEADER_BYTES:
                incoming = value.decode("latin-1")
                break
        request_id = accept_request_id(incoming) or str(uuid.uuid4())
        scope["request_id"] = request_id
        token = request_id_var.set(request_id)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != _HEADER_BYTES]
                headers.append((_HEADER_BYTES, request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            request_id_var.reset(token)
