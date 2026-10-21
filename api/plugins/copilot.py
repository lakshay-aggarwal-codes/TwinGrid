"""Plugin: Copilot v1 (Task 14). ``POST /api/copilot/ask``: rule-based answers from cited evidence. No language model.

* Any signed-in user, demo viewers included: the route only reads. There is no write tool (``src/copilot/tools.py``).
* Rate limit: the existing ``state`` request class (no new setting); errors use the application's problem body.
* Logging: request id, mode, intent and evidence count only. The question, history, alert text and telemetry values are
  never logged.
* The loaders below call the EXISTING route functions/repositories (``explainability.alert_explanation`` and
  ``model_passport``, ``data_repository.get_alert``); the rule maths is not repeated.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.errors import ApiError
from api.middleware.request_id import get_request_id
from api.plugins import explainability
from api.rate_limit import http_limit
from api.repositories import data_repository
from database import get_db
from models.db_models import Sensor, TelemetrySample, User
from src.copilot import answer as copilot_answer
from src.copilot import tools
from src.copilot.schemas import AskRequest, AskResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["copilot"])


def _loaders(db: AsyncSession, user: User) -> tools.ToolContext:
    async def load_alert(alert_id: str) -> Optional[dict[str, Any]]:
        if not alert_id.isdigit() or len(alert_id) > 18:  # not an id of this database: the alert does not exist
            return None
        alert = await data_repository.get_alert(db, int(alert_id))
        if alert is None:
            return None
        explanation = await explainability.alert_explanation(alert.id, user, db)  # the endpoint's own logic
        return {
            "alert": {
                "id": alert.id, "created_at": alert.created_at, "message": alert.message,
                "severity": alert.severity, "type": alert.type, "origin": alert.origin, "score": alert.score,
            },
            "explanation": explanation,
        }  # fmt: skip

    async def load_signal(signal: str) -> Optional[dict[str, Any]]:
        row = (
            await db.execute(
                select(TelemetrySample, Sensor)
                .join(Sensor, Sensor.id == TelemetrySample.sensor_id)
                .where(
                    Sensor.external_id == signal, TelemetrySample.stream_id == "live", TelemetrySample.quality == "good"
                )
                .order_by(TelemetrySample.ts_event.desc(), TelemetrySample.id.desc())
                .limit(1)
            )
        ).first()
        if row is None:
            return None
        sample, sensor = row
        return {
            "value": sample.value, "observed_at": sample.ts_event, "unit": sensor.unit,
            "origin": sample.origin, "measurand": sensor.measurand,
        }  # fmt: skip

    async def load_passport() -> Optional[dict[str, Any]]:
        try:
            return await explainability.model_passport(user)
        except ApiError:
            return None

    return tools.ToolContext(
        now=datetime.now(timezone.utc), load_alert=load_alert, load_signal=load_signal, load_passport=load_passport
    )


@router.post("/api/copilot/ask", dependencies=[Depends(http_limit("state"))], response_model=AskResponse)
async def ask(
    body: AskRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    inp = copilot_answer.AskInput(
        question=body.question,
        kind=body.context.kind,
        context_id=body.context.id,
        history=[h.model_dump() for h in body.history],
    )
    try:
        result = await copilot_answer.answer_question(inp, _loaders(db, user))
    except tools.NotFound:
        raise ApiError(404, "not_found", "Alert not found") from None
    request_id = get_request_id(request.scope)
    logger.info(
        "copilot_ask request_id=%s mode=%s intent=%s evidence=%d",
        request_id, result.mode, result.intent, len(result.evidence),
    )  # fmt: skip
    return {
        "request_id": request_id,
        "mode": result.mode,
        "answer": result.answer,
        "evidence": result.evidence,
        "unknowns": result.unknowns,
        "warnings": result.warnings,
        "links": result.links,
        "limits": result.limits,
    }
