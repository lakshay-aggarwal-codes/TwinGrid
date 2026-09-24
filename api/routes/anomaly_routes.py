from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.repositories import data_repository
from api.schemas.optimization import AnomalyScoreResponse
from api.services import anomaly_service
from database import get_db
from models.db_models import User

router = APIRouter(tags=["anomaly"])


@router.get("/api/anomaly_score")
async def anomaly_score(
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    recent_data: str = Query(..., description="JSON array of recent sensor readings, shape (12, 5)"),
) -> AnomalyScoreResponse:
    """Compute anomaly score from the last 12 timesteps of 5 sensor features."""
    result = anomaly_service.score_recent_data(recent_data)
    # Only genuine alerts are persisted. Previously EVERY scoring call (including
    # "normal", "detector not available" and "error" results) wrote an Alert row,
    # so /api/alerts was flooded with non-alerts -- and the frontend scores every
    # 3 seconds.
    if result["alert"]:
        await data_repository.save_alert(
            session,
            result["score"],
            True,
            result["type"],
            result["message"],
            severity=anomaly_service.alert_severity(result["score"], result["threshold"]),
        )
    return AnomalyScoreResponse(**result)


@router.get("/api/alerts")
async def list_alerts(
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200, description="Max number of alerts to return"),
) -> list[dict]:
    """List recent alerts, ordered by created_at descending."""
    alerts = await data_repository.list_recent_alerts(session, limit)
    return [
        {
            "id": a.id,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "type": a.type,
            "message": a.message,
            "severity": a.severity or "INFO",
            "score": a.score,
            "alert": a.alert,
        }
        for a in alerts
    ]