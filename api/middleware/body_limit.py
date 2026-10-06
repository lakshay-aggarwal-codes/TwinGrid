"""Request-body size cap (T14): bodies over MAX_BODY_BYTES (default 1 MiB) are rejected with 413.

* A declared ``Content-Length`` over the cap is rejected before anything is read.
* Without one (chunked), bytes are counted as the app reads them; the read that crosses the cap raises
  ``ApiError(413)``, which FastAPI re-raises as-is and the HTTP-exception handler renders (a plain exception
  would have been turned into a 400 by FastAPI's body parsing).

Pure ASGI. The limit is read per request (api/config.py ``max_body_bytes``).
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api import config
from api.errors import ApiError, problem_response


def _too_large(limit: int) -> ApiError:
    return ApiError(413, "payload_too_large", f"Request body too large (max {limit} bytes)")


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = config.max_body_bytes()
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    break  # malformed: fall back to counting
                if declared > limit:
                    exc = _too_large(limit)
                    response = problem_response(scope, 413, exc.detail, code=exc.code)
                    await response(scope, receive, send)
                    return
                break

        received = 0

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _too_large(limit)
            return message

        await self.app(scope, counting_receive, send)
