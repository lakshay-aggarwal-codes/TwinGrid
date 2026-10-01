from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user, require_operator
from api.config import MAX_RECENT_DATA_CHARS
from api.rate_limit import http_limit
from api.repositories import data_repository
from api.schemas.optimization import AnomalyScoreResponse
from api.services import anomaly_service, audit_service, webhook_service
from api.services.webhook_security import WebhookURLError, validate_webhook_url
from database import get_db
from models.db_models import User

router = APIRouter(tags=["anomaly"])


@router.get("/api/anomaly_score", dependencies=[Depends(http_limit("anomaly_score"))])
async def anomaly_score(
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    recent_data: str = Query(
        ...,
        max_length=MAX_RECENT_DATA_CHARS,
        description="JSON array of recent sensor readings, shape (12, 5)",
    ),
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
        # Webhook subscribers get pushed the same alert instead of having to
        # poll GET /api/alerts. No-ops instantly if nobody's registered.
        await webhook_service.dispatch_alert(
            {"score": result["score"], "type": result["type"], "message": result["message"]}
        )
    return AnomalyScoreResponse(**result)


@router.post("/api/webhooks", dependencies=[Depends(http_limit("webhook"))])
async def register_webhook(
    _user: Annotated[User, Depends(require_operator)],
    url: str = Query(..., max_length=2048),
) -> dict:
    """Register a URL to receive POSTed alert events (see
    api/services/webhook_service.py). Operator-only. The URL must be https and
    resolve to a public address (SSRF guard: api/services/webhook_security.py).
    Returns the current subscriber list."""
    from src.webhook_registry import SubscriberLimitError, register

    try:
        # DNS lookup blocks, so keep it off the event loop.
        await run_in_threadpool(validate_webhook_url, url)
    except WebhookURLError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    try:
        return {"subscribers": register(url)}
    except SubscriberLimitError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/api/webhooks", dependencies=[Depends(http_limit("webhook"))])
async def unregister_webhook(
    _user: Annotated[User, Depends(require_operator)],
    url: str = Query(..., max_length=2048),
) -> dict:
    from src.webhook_registry import unregister

    return {"subscribers": unregister(url)}


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
            "acknowledged": a.acknowledged,
            "acknowledged_by": a.acknowledged_by,
            "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
        }
        for a in alerts
    ]


@router.post("/api/alerts/{alert_id}/acknowledge", dependencies=[Depends(http_limit("alert_ack"))])
async def acknowledge_alert(
    alert_id: int,
    request: Request,
    user: Annotated[User, Depends(require_operator)],
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Acknowledge an alert. Requires 'operator' role; audit-logged."""
    alert = await data_repository.acknowledge_alert(session, alert_id, acknowledged_by=user.username)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    await audit_service.log_action(
        session,
        action="alert_acknowledged",
        user=user,
        resource_type="alert",
        resource_id=alert_id,
        request=request,
    )
    return {
        "id": alert.id,
        "acknowledged": alert.acknowledged,
        "acknowledged_by": alert.acknowledged_by,
        "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
    }
