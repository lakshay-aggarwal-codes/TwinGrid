"""
Data-access layer: every direct SQLAlchemy session.add()/commit() call in
the API lives here, not scattered across route handlers. Consolidated
into one module rather than one-file-per-entity, since each function is a
single, trivial persistence call.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_models import Alert, OptimizationResult, SensorReading, SimulationRun


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
) -> None:
    session.add(Alert(score=score, alert=alert, type=type_, message=message, severity=severity))
    await session.flush()


async def list_recent_alerts(session: AsyncSession, limit: int) -> list[Alert]:
    result = await session.execute(select(Alert).order_by(Alert.created_at.desc()).limit(limit))
    return list(result.scalars().all())