"""Plugin: the alert incident workflow (Task 17).

* ``GET   /api/alerts/inbox``          -- any signed-in user: alerts with derived ``status`` and ``assignee`` (filters:
  ``status``, ``severity``, ``limit``). The core ``GET /api/alerts`` is unchanged.
* ``GET   /api/alerts/{id}/events``    -- any signed-in user: the incident timeline (oldest first).
* ``PATCH /api/alerts/{id}``           -- operator only: change ``status`` (open -> acknowledged -> resolved, re-open
  allowed), set/clear ``assignee`` (an existing operator), add a ``note``. One audit row (``alert_updated``) per call
  that changed something; denied attempts are audited by ``require_operator`` like every other operator route.

Every write goes through ``data_repository.apply_alert_workflow`` (ADR 006); this module never builds a row. Rules and
the stored-state mapping live in ``src/alert_workflow.py``. Rate limit: the existing ``alert_ack`` class.

``alert_updated`` is deliberately not added to ``audit_service.EVENT_MODES`` (that table is pinned by tests and the
audit writer does not require it); the row is written in ATOMIC mode, i.e. with the change.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user, require_operator
from api.errors import ApiError
from api.rate_limit import http_limit
from api.repositories import data_repository
from api.services import audit_service
from database import get_db
from models.db_models import Alert, User
from src import alert_workflow as wf

router = APIRouter(tags=["alerts"])

Status = Literal["open", "acknowledged", "resolved"]
Severity = Literal["INFO", "WARNING", "CRITICAL"]


def _iso(value: Optional[datetime]) -> Optional[str]:
    """RFC 3339 UTC. A naive value (SQLite returns naive datetimes) is UTC by the project's time contract."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def alert_to_dict(a: Alert) -> dict[str, Any]:
    return {
        "id": a.id,
        "created_at": _iso(a.created_at),
        "type": a.type,
        "message": a.message,
        "severity": a.severity or "INFO",
        "score": a.score,
        "alert": a.alert,
        "origin": a.origin,
        "model_version": a.model_version,
        "dedupe_key": a.dedupe_key,
        "acknowledged": a.acknowledged,
        "acknowledged_by": a.acknowledged_by,
        "acknowledged_at": _iso(a.acknowledged_at),
        "status": wf.effective_status(a.status, bool(a.acknowledged)),
        "assignee": a.assignee,
        "resolved_by": a.resolved_by,
        "resolved_at": _iso(a.resolved_at),
    }


class AlertPatch(BaseModel):
    """At least one of ``status``, ``assignee`` (null/"" clears it) or ``note`` must be present."""

    model_config = ConfigDict(extra="forbid")

    status: Optional[Status] = None
    assignee: Optional[str] = Field(default=None, max_length=wf.MAX_ASSIGNEE_CHARS)
    note: Optional[str] = Field(default=None, max_length=wf.MAX_NOTE_CHARS)


@router.get("/api/alerts/inbox")
async def alert_inbox(
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=200),
    status: Optional[Status] = Query(None),
    severity: Optional[Severity] = Query(None),
) -> list[dict[str, Any]]:
    rows = await data_repository.list_alert_inbox(session, limit, severity=severity, status=status)
    return [alert_to_dict(a) for a in rows]


@router.get("/api/alerts/{alert_id}/events")
async def alert_events(
    alert_id: int,
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    alert = await data_repository.get_alert(session, alert_id)
    if alert is None:
        raise ApiError(404, "not_found", "Alert not found")
    stored = await data_repository.list_alert_events(session, alert_id)
    entries = wf.build_timeline(
        created_at=alert.created_at,
        acknowledged=bool(alert.acknowledged),
        acknowledged_by=alert.acknowledged_by,
        acknowledged_at=alert.acknowledged_at,
        events=[
            {
                "created_at": e.created_at,
                "actor": e.actor,
                "kind": e.kind,
                "from_status": e.from_status,
                "to_status": e.to_status,
                "assignee": e.assignee,
                "note": e.note,
            }
            for e in stored
        ],
    )
    return {
        "alert_id": alert_id,
        "entries": [
            {"at": _iso(t.at), "kind": t.kind, "actor": t.actor, "summary": t.summary, "note": t.note} for t in entries
        ],
    }


@router.patch("/api/alerts/{alert_id}", dependencies=[Depends(http_limit("alert_ack"))])
async def update_alert(
    alert_id: int,
    body: AlertPatch,
    request: Request,
    user: Annotated[User, Depends(require_operator)],
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    assignee_given = "assignee" in body.model_fields_set
    note = body.note.strip() if body.note is not None else None
    if note == "":
        raise ApiError(422, "validation_error", "A note cannot be empty")
    if body.status is None and not assignee_given and note is None:
        raise ApiError(422, "validation_error", "Nothing to change: send status, assignee or note")

    assignee: Any = data_repository.UNCHANGED
    if assignee_given:
        name = (body.assignee or "").strip()
        if name:
            found = (await session.execute(select(User).where(User.username == name))).scalar_one_or_none()
            if found is None or not found.is_operator():
                raise ApiError(422, "unknown_assignee", "The assignee must be an existing operator")
        assignee = name or None

    try:
        result = await data_repository.apply_alert_workflow(
            session, alert_id, actor=user.username, status=body.status, assignee=assignee, note=note
        )
    except wf.InvalidTransition as exc:
        raise ApiError(409, "invalid_transition", f"{exc}; allowed: {', '.join(exc.allowed) or 'none'}") from exc
    if result is None:
        raise ApiError(404, "not_found", "Alert not found")
    alert, events = result
    if events:
        await audit_service.log_action(
            session,
            action="alert_updated",
            user=user,
            resource_type="alert",
            resource_id=alert_id,
            details={
                "to_status": body.status,
                "assignee_changed": any(e.kind == "assigned" for e in events),
                "assignee": alert.assignee if assignee_given else None,
                "note_added": note is not None,
                "note_chars": len(note) if note is not None else 0,
            },
            request=request,
        )
    return alert_to_dict(alert)
