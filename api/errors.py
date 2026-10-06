"""One error model for the whole API (T14, roadmap section 8.2).

Every failure response is ``application/problem+json``::

    {"type": "urn:twingrid:error:<code>", "title": "...", "status": 404, "detail": "<string>",
     "instance": "<request path>", "request_id": "...", "errors": [...]}      # errors: 422 only

* ``detail`` stays a PLAIN STRING and stays the primary human message, so existing clients
  (twin-stream-insight-main/src/api/apiClient.ts reads ``detail`` as a string) keep working. FastAPI's own
  422 used a list there; it is now a one-line summary and the structured list moved to ``errors``.
* ``errors[]`` items are ``{loc, msg, type}`` only. Pydantic's ``input`` (the caller's raw value) and ``ctx``
  are DROPPED: they echo request data back and can carry exception objects.
* Unhandled exceptions return a generic 500. The exception text, traceback and file paths go to the server log
  (with the request id) and never to the client.
* ``instance`` is the request PATH only (no query string: WebSocket/legacy URLs may carry tokens there).

``ErrorBoundaryMiddleware`` turns an unhandled exception into that response INSIDE the CORS/request-id layers,
so the 500 carries CORS and X-Request-ID headers and the exception is not re-raised into the server.
Rollback: stop calling ``register_exception_handlers`` / drop the middleware in api/main.py.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.middleware.request_id import HEADER_NAME, get_request_id

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"
TYPE_PREFIX = "urn:twingrid:error:"

# status -> default error code. A route can be more specific with ApiError(code=...).
STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
    504: "gateway_timeout",
}

GENERIC_500_DETAIL = "Internal server error"
_MAX_DETAIL_CHARS = 500


class ApiError(HTTPException):
    """HTTPException with a machine-readable ``code`` (-> ``urn:twingrid:error:<code>``)."""

    def __init__(self, status_code: int, code: str, detail: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code


def _title(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"


def problem_response(
    scope: Scope,
    status: int,
    detail: str,
    *,
    code: str | None = None,
    errors: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the section 8.2 body for the request in ``scope``."""
    code = code or STATUS_CODES.get(status) or ("client_error" if status < 500 else "server_error")
    request_id = get_request_id(scope)
    body: dict[str, Any] = {
        "type": f"{TYPE_PREFIX}{code}",
        "title": _title(status),
        "status": status,
        "detail": detail,
        "instance": scope.get("path", ""),
        "request_id": request_id,
    }
    if errors is not None:
        body["errors"] = errors
    out_headers = {k: v for k, v in (headers or {}).items() if k.lower() != HEADER_NAME.lower()}
    out_headers[HEADER_NAME] = request_id
    return JSONResponse(body, status_code=status, headers=out_headers, media_type=PROBLEM_MEDIA_TYPE)


# ----------------------------------------------------------------------------- handlers


async def http_exception_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, StarletteHTTPException)
    detail = exc.detail if isinstance(exc.detail, str) and exc.detail else _title(exc.status_code)
    code = exc.code if isinstance(exc, ApiError) else None
    headers = dict(exc.headers) if exc.headers else None
    return problem_response(request.scope, exc.status_code, detail, code=code, headers=headers)


def _loc_text(loc: Any) -> str:
    return ".".join(str(part) for part in loc) if isinstance(loc, (list, tuple)) else str(loc)


async def validation_exception_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RequestValidationError)
    errors = [
        {"loc": list(err.get("loc", ())), "msg": str(err.get("msg", "")), "type": str(err.get("type", ""))}
        for err in exc.errors()
    ]
    summary = "; ".join(f"{_loc_text(e['loc'])}: {e['msg']}" for e in errors) or "Request validation failed"
    if len(summary) > _MAX_DETAIL_CHARS:
        summary = summary[: _MAX_DETAIL_CHARS - 3] + "..."
    return problem_response(request.scope, 422, summary, errors=errors)


async def rate_limit_exceeded_handler(request: Request, exc: Exception) -> Response:
    """slowapi (/auth/* routes): same body as every other 429."""
    return problem_response(request.scope, 429, f"Rate limit exceeded: {getattr(exc, 'detail', 'too many requests')}")


def unhandled_response(scope: Scope, exc: BaseException) -> Response:
    """Log ``exc`` server-side (with the request id) and return the generic 500. Nothing about ``exc`` is sent."""
    logger.error(
        "Unhandled exception (request_id=%s %s)",
        get_request_id(scope),
        scope.get("path", ""),
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return problem_response(scope, 500, GENERIC_500_DETAIL)


async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    return unhandled_response(request.scope, exc)


def register_exception_handlers(app: Any) -> None:
    """Install the handlers on a FastAPI app. StarletteHTTPException also covers the router's own 404/405."""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)


class ErrorBoundaryMiddleware:
    """Catch anything the route stack raises before a response started and answer with the generic 500."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            if started:  # headers already sent: cannot change the response, let the server abort it
                raise
            response = unhandled_response(scope, exc)
            await response(scope, receive, send)
