from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api import config
from api.auth import get_current_user
from api.services import anomaly_service, optimization_service
from api.services.live_broadcast_service import BROADCAST_LOOP_NAME
from api.supervisor import supervisor
from database import get_db
from models.db_models import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

_PROBE_TIMEOUT_S = 3.0
_ROOT = Path(__file__).resolve().parents[2]
_alembic_head_cache: str | None = None


@router.get("/livez")
async def liveness() -> dict[str, str]:
    """Process liveness (T18). Depends on NOTHING: no database, no auth, no Redis, no models. If this answers, the
    event loop is running; whether the app can do useful work is /readyz's question."""
    return {"status": "alive"}


def _alembic_head() -> str | None:
    """The single head revision of alembic/versions (read from the files once; no database, no env.py)."""
    global _alembic_head_cache
    if _alembic_head_cache is None:
        try:
            from alembic.config import Config
            from alembic.script import ScriptDirectory

            cfg = Config()
            cfg.set_main_option("script_location", str(_ROOT / "alembic"))
            _alembic_head_cache = ScriptDirectory.from_config(cfg).get_current_head()
        except Exception:
            logger.exception("Could not determine the Alembic head")
            return None
    return _alembic_head_cache


async def _database_revision(session: AsyncSession) -> str | None:
    try:
        row = (await session.execute(text("SELECT version_num FROM alembic_version"))).first()
    except Exception:
        return None
    return str(row[0]) if row else None


def _ping_redis() -> bool:
    from redis import Redis

    client = Redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=1, socket_timeout=1)
    try:
        return bool(client.ping())
    finally:
        client.close()


async def _redis_state() -> str:
    if not os.getenv("REDIS_URL", "").strip():
        return "not_configured"
    try:
        return "ok" if await asyncio.wait_for(asyncio.to_thread(_ping_redis), _PROBE_TIMEOUT_S) else "degraded"
    except Exception:
        return "degraded"


def _model_state() -> dict[str, str]:
    detector = anomaly_service.get_pipeline().snapshot().get("status")
    broken = (anomaly_service.STATUS_UNAVAILABLE, anomaly_service.STATUS_ERROR)
    return {
        "optimizer": "loaded" if optimization_service.get_optimizer() is not None else "not_loaded",
        "anomaly_detector": "degraded" if detector in broken else "ok",
    }


@router.get("/readyz")
async def readiness(session: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Readiness (T18, roadmap section 8.5). 200 only if ALL of:

    * the database answers ``SELECT 1``;
    * the schema is at the Alembic head (skip with READYZ_CHECK_SCHEMA=false for create_all-built dev databases);
    * the broadcast loop's heartbeat is fresh (< 3 x interval + 5 s) and the supervisor has not given up on it.

    Redis and model state are REPORTED under ``degraded`` but never fail the probe. Bodies carry statuses and
    counts only: no exception text, paths or connection strings.
    """
    checks: dict[str, Any] = {}

    try:
        await asyncio.wait_for(session.execute(text("SELECT 1")), _PROBE_TIMEOUT_S)
        checks["database"] = "ok"
    except Exception:
        logger.exception("Readiness: database unreachable")
        checks["database"] = "fail"

    if not config.readyz_check_schema():
        checks["schema"] = "skipped"
    elif checks["database"] != "ok":
        checks["schema"] = "unknown"
    else:
        head, current = _alembic_head(), await _database_revision(session)
        checks["schema"] = "ok" if head is not None and current == head else "behind" if current else "missing"

    state = supervisor.state(BROADCAST_LOOP_NAME)
    if state is None:
        checks["broadcast"] = "not_running"
    elif state.gave_up:
        checks["broadcast"] = "gave_up"
    elif not supervisor.heartbeat_fresh(BROADCAST_LOOP_NAME):
        checks["broadcast"] = "stale"
    else:
        checks["broadcast"] = "ok"
    age = supervisor.heartbeat_age_s(BROADCAST_LOOP_NAME)

    redis_state = await _redis_state()
    models = _model_state()
    degraded = sorted(
        name for name, value in (("redis", redis_state), *models.items()) if value in ("degraded", "not_loaded")
    )

    ready = all(checks[name] in ("ok", "skipped") for name in ("database", "schema", "broadcast"))
    body = {
        "status": "ready" if ready else "not_ready",
        "checks": checks,
        "degraded": degraded,
        "components": {"redis": redis_state, **models},
        "broadcast_heartbeat_age_s": None if age is None else round(age, 3),
        "broadcast_restarts": state.restarts if state else 0,
        "timestamp": datetime.now().isoformat(),
    }
    return JSONResponse(body, status_code=200 if ready else 503)


@router.get("/healthz", deprecated=True)
async def liveness_check(session: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """
    DEPRECATED alias (T18): use /livez (process alive) and /readyz (can serve traffic). Behaviour unchanged.

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
    except Exception:
        # Raw exception text (driver/DSN/host details) stays server-side only.
        logger.exception("Health check: database unreachable")
        raise HTTPException(status_code=503, detail="Service unavailable") from None
    return {"status": "ok", "database": "ok", "timestamp": datetime.now().isoformat()}


@router.get("/api/health")
async def health_check(_user: Annotated[User, Depends(get_current_user)]) -> dict[str, str]:
    """Health check endpoint. Requires valid JWT."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}
