"""Plugin: security response headers (Task 6). Middleware: api/middleware/security_headers.py.

Wraps the finished middleware stack so the headers are on every response, including the 413/500 bodies produced
by inner middleware. Order of wrapping across plugins follows plugin name order (later = further out).
"""

from __future__ import annotations

from fastapi import FastAPI
from starlette.types import ASGIApp

from api.middleware.security_headers import SecurityHeadersMiddleware


def setup(app: FastAPI) -> None:
    previous = app.build_middleware_stack

    def build() -> ASGIApp:
        return SecurityHeadersMiddleware(previous())

    app.build_middleware_stack = build  # type: ignore[method-assign]
