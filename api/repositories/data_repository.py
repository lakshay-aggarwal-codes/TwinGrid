"""
Data-access layer: every direct SQLAlchemy session.add()/commit() call in
the API lives here, not scattered across route handlers. Consolidated
into one module rather than one-file-per-entity, since each function is a
single, trivial persistence call.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_models import Alert, OptimizationResult, SensorReading, SimulationRun
from src.timeutil import utc_now


async def save_sensor_reading(
    session: AsyncSession, state_dict: dict[str, Any], source: str, simulation_run_id: int | None = None
) -> None:
    session.add(SensorReading.from_state_dict(state_dict, source, simulation_run_id=simulation_run_id))
    await session.flush()


async def save_sensor_readings_bulk(
    session: AsyncSession, records: list[dict[str, Any]], source: str, simulation_run_id: int | None = None
) -> None:
    for record in records:
        session.add(SensorReading.from_state_dict(record, source, simulation_run_id=simulation_run_id))
    await session.flush()


async def save_simulation_run(
    session: AsyncSession, hours: int, utilisation: float, stress: float, result_snapshot: list[dict[str, Any]]
) -> SimulationRun:
    run = SimulationRun(hours=hours, utilisation=utilisation, stress=stress, result_snapshot=result_snapshot)
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
