from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from database import get_db
from models.db_models import User

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def liveness_check(session: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """
    Unauthenticated liveness/readiness check for infrastructure (Docker
    HEALTHCHECK, load balancers, uptime monitors) -- deliberately separate
    from GET /api/health, which requires a JWT and exists for authenticated
    clients confirming the API is reachable, not for infrastructure that
    has no way to hold a token.

    Returns HTTP 503 (not 200-with-a-status-field) when the DB is
    unreachable, so a plain `curl -f` correctly detects failure -- a 200
    response with a "degraded" string inside it would NOT fail curl -f,
    and would make the Docker HEALTHCHECK below meaningless.
    """
    try:
        await session.execute(text("SELECT 1"))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unreachable: {e}")
    return {"status": "ok", "database": "ok", "timestamp": datetime.now().isoformat()}


@router.get("/api/health")
async def health_check(_user: Annotated[User, Depends(get_current_user)]) -> dict[str, str]:
    """Health check endpoint. Requires valid JWT."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}