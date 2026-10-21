"""Demo sessions are read-only (Task 13, roadmap section 8.3).

A token minted by ``POST /auth/demo-session`` carries ``demo=true``. This module denies such a token every write:

* ``require_not_demo`` -- a dependency, wired explicitly into ``POST /api/runs``.
* ``DemoReadOnlyMiddleware`` -- installed by ``api/plugins/demo_session.py``. Any POST/PUT/PATCH/DELETE carrying a valid
  demo token is refused with ``403`` ``demo_read_only`` BEFORE routing, so a write route added later is covered without
  anyone remembering to guard it. The few writes a read-only visitor needs stay open (``ALLOWED_DEMO_WRITES``).

Only a token whose signature and expiry verify is looked at; anything else passes through to the normal 401 handling.
A normal viewer token has no ``demo`` claim and is never affected.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from starlette.types import ASGIApp, Receive, Scope, Send

from api import auth
from api.errors import ApiError, problem_response

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Writes that do not change facility state and that a read-only visitor needs, or that are public anyway.
ALLOWED_DEMO_WRITES = frozenset(
    {
        "/auth/ws-ticket",  # the live feed
        "/auth/refresh",  # a demo session has no refresh token: this answers 401 as for any unknown token
        "/auth/logout",
        "/auth/login",
        "/auth/demo-session",
        "/client-errors",
        "/api/client-errors",
        "/api/copilot/ask",  # Task 27: POST but read-only (no write tool, src/copilot/tools.py); demo viewers are meant to use it
    }
)

DEMO_READ_ONLY_CODE = "demo_read_only"
DEMO_READ_ONLY_DETAIL = "Demo sessions are read-only."


async def require_not_demo(claims: Annotated[dict, Depends(auth.get_token_claims)]) -> None:
    """403 ``demo_read_only`` when the bearer token is a demo token."""
    if auth.is_demo_claims(claims):
        raise ApiError(403, DEMO_READ_ONLY_CODE, DEMO_READ_ONLY_DETAIL)


def _bearer(scope: Scope) -> str | None:
    for name, value in scope.get("headers") or []:
        if name == b"authorization":
            scheme, _, token = value.decode("latin-1").partition(" ")
            if scheme.lower() == "bearer" and token.strip():
                return token.strip()
    return None


def _is_demo_token(token: str) -> bool:
    try:
        return auth.is_demo_claims(auth.decode_token(token))
    except Exception:  # noqa: BLE001 - an unusable token is the route's 401, not ours
        return False


class DemoReadOnlyMiddleware:
    """Pure ASGI middleware: see the module docstring."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        is_write = scope["type"] == "http" and scope.get("method") in WRITE_METHODS
        if is_write and scope.get("path") not in ALLOWED_DEMO_WRITES:
            token = _bearer(scope)
            if token is not None and _is_demo_token(token):
                response = problem_response(scope, 403, DEMO_READ_ONLY_DETAIL, code=DEMO_READ_ONLY_CODE)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
