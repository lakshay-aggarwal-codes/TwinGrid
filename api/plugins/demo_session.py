"""Plugin: ``POST /auth/demo-session`` -- an anonymous, read-only demo viewer session (Task 13, section 8.3).

* ``DEMO_PUBLIC_ENABLED`` false/unset -> 404 ``not_found``, the same answer as an unknown route.
* Enabled -> an access token (``DEMO_SESSION_MINUTES``, default 30) for the seeded ``demo_viewer`` with claims
  ``sub``, ``role=viewer``, ``demo=true``, ``exp``. NO refresh token is issued: the session ends when the token
  expires or the client drops it.
* 503 ``demo_unavailable`` when ``demo_viewer`` is missing (or is not a viewer: a promoted account is never handed out).
* ``DEMO_SESSION_RATE_LIMIT`` (default 20/hour) per client IP -> 429 ``rate_limited``.
* Audit row ``demo_session_issued`` (best-effort).
* ``setup`` installs the read-only guard (``api/demo_guard.py``) for every write route.

Errors use the repository's one error model (problem+json, code in ``type`` = ``urn:twingrid:error:<code>``).
Settings are read from the environment on every request (docs/env/T13.md).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from jose import jwt
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api import auth
from api.demo_guard import DemoReadOnlyMiddleware
from api.errors import ApiError
from api.rate_limit import _hit, client_ip, limiter, parse_rate
from api.services import audit_service
from database import get_db
from models.db_models import USER_ROLE_VIEWER

router = APIRouter(prefix="/auth", tags=["auth"])

DEMO_USERNAME = "demo_viewer"
DEFAULT_RATE_LIMIT = "20/hour"
DEFAULT_SESSION_MINUTES = 30
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def demo_public_enabled() -> bool:
    return os.getenv("DEMO_PUBLIC_ENABLED", "").strip().lower() in _TRUE_VALUES


def session_minutes() -> int:
    try:
        value = int(os.getenv("DEMO_SESSION_MINUTES", "").strip() or DEFAULT_SESSION_MINUTES)
    except ValueError:
        return DEFAULT_SESSION_MINUTES
    return value if 1 <= value <= 24 * 60 else DEFAULT_SESSION_MINUTES


def rate_limit() -> tuple[int, int]:
    try:
        return parse_rate(os.getenv("DEMO_SESSION_RATE_LIMIT", "").strip() or DEFAULT_RATE_LIMIT)
    except ValueError:
        return parse_rate(DEFAULT_RATE_LIMIT)


class DemoSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str = USER_ROLE_VIEWER
    demo: bool = True


def mint_demo_token(user_id: int, minutes: int) -> str:
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "role": USER_ROLE_VIEWER,
        "demo": True,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes),
    }
    return jwt.encode(claims, auth.SECRET_KEY, algorithm=auth.ALGORITHM)


@router.post("/demo-session", response_model=DemoSessionResponse)
async def create_demo_session(request: Request, session: AsyncSession = Depends(get_db)) -> DemoSessionResponse:
    if not demo_public_enabled():
        raise ApiError(404, "not_found", "Not Found")
    if limiter.enabled:
        count, window = rate_limit()
        retry_after = _hit("demo_session", f"ip:{client_ip(request)}", count, window)
        if retry_after is not None:
            raise ApiError(429, "rate_limited", "Too many demo sessions", {"Retry-After": str(retry_after)})
    user = await auth.get_user_by_username(session, DEMO_USERNAME)
    if user is None or user.role != USER_ROLE_VIEWER:
        raise ApiError(503, "demo_unavailable", "The demo is not available right now.")
    minutes = session_minutes()
    token = mint_demo_token(user.id, minutes)
    await audit_service.log_action_best_effort(
        action="demo_session_issued",
        user=user,
        resource_type="user",
        resource_id=user.id,
        details={"expires_in_s": minutes * 60},
        request=request,
    )
    return DemoSessionResponse(access_token=token, expires_in=minutes * 60)


def setup(app: Any) -> None:
    """Install the read-only guard. Runs once at start-up (plugin loader)."""
    app.add_middleware(DemoReadOnlyMiddleware)
