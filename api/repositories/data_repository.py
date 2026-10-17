"""
Data-access layer: every direct SQLAlchemy session.add()/commit() call in
the API lives here, not scattered across route handlers. Consolidated
into one module rather than one-file-per-entity, since each function is a
single, trivial persistence call.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_models import Alert, AlertEvent, OptimizationResult, SensorReading, SimulationRun
from src import alert_workflow
from src.timeutil import utc_now
from src.versions import active_physics_version

_SIMULATED = "simulated"  # every writer in this module stores simulator output


async def save_sensor_readings_bulk(
    session: AsyncSession,
    records: list[dict[str, Any]],
    source: str,
    simulation_run_id: int | None = None,
    *,
    physics_version: str | None = None,
) -> None:
    version = physics_version or active_physics_version()
    for record in records:
        session.add(
            SensorReading.from_state_dict(
                record, source, simulation_run_id=simulation_run_id, origin=_SIMULATED, physics_version=version
            )
        )
    await session.flush()


async def save_simulation_run(
    session: AsyncSession,
    hours: int,
    utilisation: float,
    stress: float,
    result_snapshot: list[dict[str, Any]],
    *,
    physics_version: str | None = None,
) -> SimulationRun:
    run = SimulationRun(
        hours=hours,
        utilisation=utilisation,
        stress=stress,
        result_snapshot=result_snapshot,
        physics_version=physics_version or active_physics_version(),
    )
    session.add(run)
    await session.flush()
    return run


async def save_optimization_result(session: AsyncSession, **fields: Any) -> OptimizationResult:
    opt = OptimizationResult(**fields)
    session.add(opt)
    await session.flush()
    return opt


async def save_alert(
    session: AsyncSession,
    score: float,
    alert: bool,
    type_: str,
    message: str,
    severity: Optional[str] = None,
    *,
    dedupe_key: Optional[str] = None,
    model_version: Optional[str] = None,
    origin: Optional[str] = None,
    sensor_reading_id: Optional[int] = None,
) -> Alert:
    """Persist an alert and return it.

    With a ``dedupe_key`` this is idempotent: the key is unique (migration M2), so a second
    call for the same anomaly episode returns the EXISTING row instead of inserting another.
    """
    if dedupe_key is not None:
        existing = await get_alert_by_dedupe_key(session, dedupe_key)
        if existing is not None:
            return existing
    row = Alert(
        score=score,
        alert=alert,
        type=type_,
        message=message,
        severity=severity,
        dedupe_key=dedupe_key,
        model_version=model_version,
        origin=origin,
        sensor_reading_id=sensor_reading_id,
    )
    if dedupe_key is None:
        session.add(row)
        await session.flush()
        return row
    try:
        # SAVEPOINT: a lost race on the unique key must not poison the caller's transaction.
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        existing = await get_alert_by_dedupe_key(session, dedupe_key)
        if existing is None:
            raise
        return existing
    return row


async def get_alert_by_dedupe_key(session: AsyncSession, dedupe_key: str) -> Optional[Alert]:
    result = await session.execute(select(Alert).where(Alert.dedupe_key == dedupe_key))
    return result.scalar_one_or_none()


async def update_alert_severity(
    session: AsyncSession, dedupe_key: str, severity: str, score: float, message: Optional[str] = None
) -> Optional[Alert]:
    """Escalate an open episode's alert in place (never creates another row)."""
    alert = await get_alert_by_dedupe_key(session, dedupe_key)
    if alert is None:
        return None
    alert.severity = severity
    alert.score = score
    if message is not None:
        alert.message = message
    await session.flush()
    return alert


async def list_recent_alerts(session: AsyncSession, limit: int) -> list[Alert]:
    result = await session.execute(select(Alert).order_by(Alert.created_at.desc()).limit(limit))
    return list(result.scalars().all())


async def get_alert(session: AsyncSession, alert_id: int) -> Optional[Alert]:
    return await session.get(Alert, alert_id)


async def acknowledge_alert(session: AsyncSession, alert_id: int, acknowledged_by: str) -> Optional[Alert]:
    """Mark an alert acknowledged. Returns None if the alert doesn't exist.
    Idempotent: acknowledging an already-acknowledged alert just updates who/when."""
    alert = await session.get(Alert, alert_id)
    if alert is None:
        return None
    alert.acknowledged = True
    alert.acknowledged_by = acknowledged_by
    alert.acknowledged_at = utc_now()
    await session.flush()
    return alert


# ----------------------------------------------------------------------------- Task 17: incident workflow
# Same rule as every other write in this module (ADR 006): the plugin api/plugins/alerts_workflow.py never touches
# an Alert/AlertEvent row itself, it calls these.

UNCHANGED: Any = object()  # "leave the assignee as it is" (None means "unassign")


async def apply_alert_workflow(
    session: AsyncSession,
    alert_id: int,
    *,
    actor: str,
    status: Optional[str] = None,
    assignee: Any = UNCHANGED,
    note: Optional[str] = None,
) -> Optional[tuple[Alert, list[AlertEvent]]]:
    """Apply one operator action to an alert and append its timeline events. ``None`` if the alert does not exist.

    Raises ``alert_workflow.InvalidTransition`` (nothing is changed) for a status move the lifecycle does not allow.
    Only the legacy ``acknowledged*`` columns are kept consistent: acknowledging sets them, re-opening clears them,
    so ``POST /api/alerts/{id}/acknowledge`` and this path never disagree.
    """
    alert = await session.get(Alert, alert_id)
    if alert is None:
        return None
    now = utc_now()
    events: list[AlertEvent] = []
    current = alert_workflow.effective_status(alert.status, bool(alert.acknowledged))

    if status is not None:
        alert_workflow.check_transition(current, status)  # raises before any change
        if status == alert_workflow.ACKNOWLEDGED:
            alert.acknowledged, alert.acknowledged_by, alert.acknowledged_at = True, actor, now
            alert.resolved_by = alert.resolved_at = None
        elif status == alert_workflow.RESOLVED:
            alert.resolved_by, alert.resolved_at = actor, now
        else:  # re-open: the episode is live again, so the previous acknowledgement no longer applies
            alert.acknowledged, alert.acknowledged_by, alert.acknowledged_at = False, None, None
            alert.resolved_by = alert.resolved_at = None
        alert.status = status
        events.append(
            AlertEvent(
                alert_id=alert.id, created_at=now, actor=actor, kind="status", from_status=current, to_status=status
            )
        )

    if assignee is not UNCHANGED and (assignee or None) != alert.assignee:
        alert.assignee = assignee or None
        events.append(
            AlertEvent(alert_id=alert.id, created_at=now, actor=actor, kind="assigned", assignee=alert.assignee)
        )

    if note is not None:
        events.append(AlertEvent(alert_id=alert.id, created_at=now, actor=actor, kind="note", note=note))

    session.add_all(events)
    await session.flush()
    return alert, events


async def list_alert_inbox(
    session: AsyncSession, limit: int, *, severity: Optional[str] = None, status: Optional[str] = None
) -> list[Alert]:
    """Newest first. ``status`` is the DERIVED lifecycle state (src.alert_workflow.effective_status), applied in SQL
    so the limit counts matching rows."""
    stmt = select(Alert).order_by(Alert.created_at.desc(), Alert.id.desc()).limit(limit)
    if severity is not None:
        stmt = stmt.where(Alert.severity == severity)
    not_resolved = or_(Alert.status.is_(None), Alert.status != alert_workflow.RESOLVED)
    if status == alert_workflow.RESOLVED:
        stmt = stmt.where(Alert.status == alert_workflow.RESOLVED)
    elif status == alert_workflow.ACKNOWLEDGED:
        stmt = stmt.where(not_resolved, Alert.acknowledged.is_(True))
    elif status == alert_workflow.OPEN:
        stmt = stmt.where(not_resolved, Alert.acknowledged.is_(False))
    return list((await session.execute(stmt)).scalars().all())


async def list_alert_events(session: AsyncSession, alert_id: int) -> list[AlertEvent]:
    result = await session.execute(
        select(AlertEvent).where(AlertEvent.alert_id == alert_id).order_by(AlertEvent.created_at, AlertEvent.id)
    )
    return list(result.scalars().all())
