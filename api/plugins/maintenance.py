"""Plugin: asset health and maintenance work orders (Task 28).

* ``GET   /api/maintenance/health``               -- any signed-in user. Per-asset health from stored telemetry and the
  degradation TREND of each sensor (``src/maintenance_health.py``: a rule on simulated data, not a failure prediction).
  There is no remaining-life estimate (``remaining_life.available`` is false and says why). Read-only.
* ``GET   /api/maintenance/work-orders``          -- any signed-in user. Filters: ``status``, ``asset``, ``limit``.
* ``GET   /api/maintenance/work-orders/{id}``     -- any signed-in user. The order, its history and the moves it allows.
* ``POST  /api/maintenance/work-orders``          -- operator or admin. From nothing (manual), from an alert, or from a
  health row. An alert or asset that does not exist is a 404; nothing is recorded.
* ``PATCH /api/maintenance/work-orders/{id}``     -- operator or admin. Title, description, priority, assignee; not once
  the order is done or cancelled.
* ``POST  /api/maintenance/work-orders/{id}/status`` -- operator or admin. open -> in_progress -> done; cancel from open or
  in progress; done and cancelled are final.

A work order is a RECORD: nothing is dispatched and no equipment is changed. There is no DELETE: cancelling is the way to
retire an order, so the history stays. Each change writes one atomic audit row (``work_order_created`` /
``work_order_updated`` / ``work_order_status_changed``; not added to ``audit_service.EVENT_MODES``, which a test pins); a
refused role writes a best-effort ``permission_denied``. Rate limits: ``telemetry_read`` for health, ``alert_ack`` for writes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.errors import ApiError
from api.rate_limit import http_limit
from api.repositories import data_repository, work_order_repository
from api.serialization import to_jsonable
from api.services import audit_service
from database import get_db
from models.db_models import Asset, Sensor, TelemetrySample, User, WorkOrder
from src import maintenance_health as health
from src import work_orders as rules
from src.timeutil import utc_now

router = APIRouter(tags=["maintenance"])

MAX_SAMPLES_PER_SENSOR = 5000
Priority = Literal["low", "medium", "high"]
Status = Literal["open", "in_progress", "done", "cancelled"]


# ----------------------------------------------------------------------------- request bodies


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["manual", "alert", "health"] = "manual"
    alert_id: Optional[int] = Field(None, ge=1)  # kind=alert
    measurand: Optional[str] = Field(None, max_length=64)  # kind=health (optional: the whole asset when absent)


class WorkOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(None, max_length=rules.MAX_TITLE_CHARS)
    description: Optional[str] = Field(None, max_length=rules.MAX_DESCRIPTION_CHARS)
    priority: Priority = "medium"
    assignee: Optional[str] = Field(None, max_length=rules.MAX_ASSIGNEE_CHARS)
    asset_external_id: Optional[str] = Field(None, max_length=128)
    source: Source = Source()

    @model_validator(mode="after")
    def _check(self) -> "WorkOrderCreate":
        kind = self.source.kind
        if kind == "alert" and self.source.alert_id is None:
            raise ValueError("source.alert_id is required for an order raised from an alert")
        if kind != "alert" and self.source.alert_id is not None:
            raise ValueError("source.alert_id is only for an order raised from an alert")
        if kind == "health" and not self.asset_external_id:
            raise ValueError("asset_external_id is required for an order raised from a health row")
        if kind != "health" and self.source.measurand is not None:
            raise ValueError("source.measurand is only for an order raised from a health row")
        if kind == "manual" and not (self.title and self.title.strip()):
            raise ValueError("title is required for a manual work order")
        return self


class WorkOrderPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(None, min_length=1, max_length=rules.MAX_TITLE_CHARS)
    description: Optional[str] = Field(None, max_length=rules.MAX_DESCRIPTION_CHARS)
    priority: Optional[Priority] = None
    assignee: Optional[str] = Field(None, max_length=rules.MAX_ASSIGNEE_CHARS)  # null clears it


class StatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Status
    note: Optional[str] = Field(None, max_length=rules.MAX_NOTE_CHARS)


# ----------------------------------------------------------------------------- roles


async def _deny(user: User, request: Request, required: str) -> None:
    await audit_service.log_action_best_effort(
        action="permission_denied",
        user=user,
        resource_type="endpoint",
        resource_id=f"{request.method} {request.url.path}",
        details={"required_role": required, "actual_role": user.role},
        request=request,
        outcome=audit_service.AUDIT_OUTCOME_DENIED,
    )
    raise ApiError(403, "forbidden", f"{required.capitalize()} role required")


async def require_writer(request: Request, user: Annotated[User, Depends(get_current_user)]) -> User:
    if not rules.can_write(user.role):
        await _deny(user, request, "operator")
    return user


# ----------------------------------------------------------------------------- serialisation


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def order_to_dict(o: WorkOrder) -> dict[str, Any]:
    return {
        "id": o.id,
        "created_at": _iso(o.created_at),
        "updated_at": _iso(o.updated_at),
        "created_by": o.created_by,
        "title": o.title,
        "description": o.description,
        "priority": o.priority,
        "status": o.status,
        "assignee": o.assignee,
        "asset_external_id": o.asset_external_id,
        "source_kind": o.source_kind,
        "source_ref": o.source_ref,
        "origin": o.origin,
        "next_statuses": list(rules.next_statuses(o.status)),
        "record_label": rules.RECORD_LABEL,
    }


def _event_to_dict(e: Any) -> dict[str, Any]:
    return {
        "at": _iso(e.created_at),
        "actor": e.actor,
        "kind": e.kind,
        "from_status": e.from_status,
        "to_status": e.to_status,
        "assignee": e.assignee,
        "note": e.note,
    }


# ----------------------------------------------------------------------------- health


def _epoch(ts: datetime) -> float:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.timestamp()


@router.get("/api/maintenance/health", dependencies=[Depends(http_limit("telemetry_read"))])
async def maintenance_health(
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    hours: int = Query(health.HOURS_DEFAULT, ge=health.HOURS_MIN, le=health.HOURS_MAX),
) -> dict[str, Any]:
    end = utc_now()
    start = end - timedelta(hours=hours)
    asset_query = select(Asset).where(Asset.retired_at.is_(None)).order_by(Asset.asset_type, Asset.external_id)
    assets = (await session.execute(asset_query)).scalars().all()
    sensor_query = select(Sensor).where(Sensor.retired_at.is_(None)).order_by(Sensor.id)
    sensors = (await session.execute(sensor_query)).scalars().all()
    by_asset: dict[int, list[dict[str, Any]]] = {}
    for s in sensors:
        rows = (
            await session.execute(
                select(TelemetrySample.ts_event, TelemetrySample.value, TelemetrySample.quality)
                .where(
                    TelemetrySample.sensor_id == s.id,
                    TelemetrySample.stream_id == "live",
                    TelemetrySample.ts_event >= start,
                    TelemetrySample.ts_event < end,
                )
                .order_by(TelemetrySample.ts_event)
                .limit(MAX_SAMPLES_PER_SENSOR)
            )
        ).all()
        summary = health.summarize_sensor(
            [(_epoch(ts), float(v), q == "ok") for ts, v, q in rows], s.min_valid, s.max_valid, unit=s.unit
        )
        by_asset.setdefault(s.asset_id, []).append(
            {"measurand": s.measurand, "external_id": s.external_id, "summary": summary}
        )
    asset_rows = [
        {"id": a.id, "external_id": a.external_id, "name": a.name, "asset_type": a.asset_type} for a in assets
    ]
    rows_out = health.build_assets(asset_rows, by_asset)
    return to_jsonable(
        {
            "label": health.LABEL,
            "origin": "simulated",
            "window_hours": hours,
            "window_start": _iso(start),
            "window_end": _iso(end),
            "counts": health.counts(rows_out),
            "remaining_life": dict(health.REMAINING_LIFE),
            "rules": {
                "min_valid_samples": health.MIN_SAMPLES,
                "invalid_share": {"watch": health.INVALID_WATCH, "warning": health.INVALID_WARNING},
                "drift_pct_of_range": {"watch": health.DRIFT_WATCH_PCT, "warning": health.DRIFT_WARNING_PCT},
            },
            "assets": rows_out,
        }
    )


# ----------------------------------------------------------------------------- work orders


async def _asset_or_404(session: AsyncSession, external_id: str) -> Asset:
    asset = (
        await session.execute(select(Asset).where(Asset.external_id == external_id, Asset.retired_at.is_(None)))
    ).scalar_one_or_none()
    if asset is None:
        raise ApiError(404, "asset_not_found", "Asset not found")
    return asset


@router.get("/api/maintenance/work-orders")
async def list_work_orders(
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    status: Optional[Status] = Query(None),
    asset: Optional[str] = Query(None, max_length=128),
    limit: int = Query(100, ge=1, le=200),
) -> list[dict[str, Any]]:
    return [order_to_dict(o) for o in await work_order_repository.list_orders(session, limit, status, asset)]


@router.get("/api/maintenance/work-orders/{order_id}")
async def get_work_order(
    order_id: int,
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await work_order_repository.get_order(session, order_id)
    if row is None:
        raise ApiError(404, "not_found", "Work order not found")
    events = await work_order_repository.list_events(session, order_id)
    return {**order_to_dict(row), "events": [_event_to_dict(e) for e in events]}


@router.post("/api/maintenance/work-orders", status_code=201, dependencies=[Depends(http_limit("alert_ack"))])
async def create_work_order(
    body: WorkOrderCreate,
    request: Request,
    user: Annotated[User, Depends(require_writer)],
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    kind = body.source.kind
    title = body.title.strip() if body.title and body.title.strip() else None
    source_ref: Optional[str] = None
    asset_external_id = body.asset_external_id or None

    if kind == "alert":
        alert = await data_repository.get_alert(session, int(body.source.alert_id or 0))
        if alert is None:
            raise ApiError(404, "alert_not_found", "Alert not found")
        source_ref = str(alert.id)
        title = title or rules.title_from_alert(alert.type, alert.message)
    if asset_external_id is not None:
        asset = await _asset_or_404(session, asset_external_id)
        if kind == "health":
            measurand = body.source.measurand
            if measurand is not None:
                known = (
                    await session.execute(
                        select(Sensor.id).where(
                            Sensor.asset_id == asset.id, Sensor.measurand == measurand, Sensor.retired_at.is_(None)
                        )
                    )
                ).first()
                if known is None:
                    raise ApiError(404, "sensor_not_found", "Sensor not found on that asset")
            source_ref = f"{asset.external_id}:{measurand}" if measurand else asset.external_id
            title = title or rules.title_from_health(asset.name, measurand, "warning")
    assert title is not None  # guaranteed by the body validator or the defaults above

    row = await work_order_repository.create_order(
        session,
        created_by=user.username,
        title=title,
        description=body.description.strip() if body.description and body.description.strip() else None,
        priority=body.priority,
        assignee=body.assignee.strip() if body.assignee and body.assignee.strip() else None,
        asset_external_id=asset_external_id,
        source_kind=kind,
        source_ref=source_ref,
    )
    await audit_service.log_action(
        session,
        action="work_order_created",
        user=user,
        resource_type="work_order",
        resource_id=row.id,
        details={
            "source_kind": kind,
            "source_ref": source_ref,
            "asset": asset_external_id,
            "priority": row.priority,
            "origin": row.origin,
        },
        request=request,
    )
    return order_to_dict(row)


@router.patch("/api/maintenance/work-orders/{order_id}", dependencies=[Depends(http_limit("alert_ack"))])
async def update_work_order(
    order_id: int,
    body: WorkOrderPatch,
    request: Request,
    user: Annotated[User, Depends(require_writer)],
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    sent = body.model_fields_set
    if not sent:
        raise ApiError(422, "empty_patch", "Send at least one field to change")
    fields: dict[str, Any] = {}
    if "title" in sent:
        fields["title"] = (body.title or "").strip()
        if not fields["title"]:
            raise ApiError(422, "empty_title", "The title cannot be empty")
    if "description" in sent:
        fields["description"] = body.description.strip() if body.description and body.description.strip() else None
    if "priority" in sent:
        if body.priority is None:
            raise ApiError(422, "bad_priority", "Priority cannot be cleared")
        fields["priority"] = body.priority
    if "assignee" in sent:
        fields["assignee"] = body.assignee.strip() if body.assignee and body.assignee.strip() else None
    try:
        row, changed = await work_order_repository.edit_order(session, order_id, actor=user.username, **fields)
    except rules.TransitionError as exc:
        raise ApiError(409, "final", "A done or cancelled work order cannot be edited") from exc
    if row is None:
        raise ApiError(404, "not_found", "Work order not found")
    if changed:
        await audit_service.log_action(
            session,
            action="work_order_updated",
            user=user,
            resource_type="work_order",
            resource_id=row.id,
            details={"changed": changed},
            request=request,
        )
    return order_to_dict(row)


@router.post("/api/maintenance/work-orders/{order_id}/status", dependencies=[Depends(http_limit("alert_ack"))])
async def change_work_order_status(
    order_id: int,
    body: StatusChange,
    request: Request,
    user: Annotated[User, Depends(require_writer)],
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    note = body.note.strip() if body.note and body.note.strip() else None
    before = await work_order_repository.get_order(session, order_id)
    previous = before.status if before is not None else None
    try:
        row = await work_order_repository.change_status(
            session, order_id, actor=user.username, to_status=body.status, note=note
        )
    except rules.TransitionError as exc:
        raise ApiError(409, exc.code, "That status change is not allowed for this work order") from exc
    if row is None:
        raise ApiError(404, "not_found", "Work order not found")
    await audit_service.log_action(
        session,
        action="work_order_status_changed",
        user=user,
        resource_type="work_order",
        resource_id=row.id,
        details={"from": previous, "to": row.status, "note_added": note is not None},
        request=request,
    )
    return order_to_dict(row)
