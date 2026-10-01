from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import get_current_user
from api.rate_limit import http_limit
from api.services import shadow_mode_service
from api.services.optimization_service import _ensure_optimizer
from models.db_models import User

router = APIRouter(tags=["shadow-mode"])


@router.post("/api/shadow_mode/sample", dependencies=[Depends(http_limit("shadow_sample"))])
async def shadow_mode_sample(_user: Annotated[User, Depends(get_current_user)]) -> dict[str, Any]:
    """One shadow-mode sample: log what PPO would have done vs. the
    rule-based baseline for the live twin's CURRENT state, without applying
    either. See api/services/shadow_mode_service.py -- not on a schedule;
    call this periodically (e.g. from an external cron/task runner) to
    build up a real comparison history."""
    optimizer = await _ensure_optimizer(alpha=0.5, beta=0.3, gamma=0.2, water_stress=0.0)
    entry = shadow_mode_service.record_comparison(optimizer)
    if entry is None:
        raise HTTPException(status_code=503, detail="Optimizer not available for shadow-mode sampling")
    return entry


@router.get("/api/shadow_mode/summary")
async def shadow_mode_summary(
    _user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(500, ge=1, le=5000, description="Max recent samples to summarize"),
) -> dict[str, Any]:
    """Agreement rate between PPO's shadowed recommendations and the
    rule-based baseline, over whatever has been logged by
    /api/shadow_mode/sample so far."""
    return shadow_mode_service.summarize(limit)
