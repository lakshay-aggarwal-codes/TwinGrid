"""
Data-access layer: every direct SQLAlchemy session.add()/commit() call in
the API lives here, not scattered across route handlers. Consolidated
into one module rather than one-file-per-entity, since each function is a
single, trivial persistence call.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_models import Alert, OptimizationResult, SensorReading, SimulationRun
from src.versions import ORIGIN_SIMULATED, PHYSICS_VERSION

# Every writer in this module persists simulator output, so each stamps
# origin/physics_version explicitly (see src/versions.py).


async def save_sensor_reading(
    session: AsyncSession, state_dict: dict[str, Any], source: str, simulation_run_id: int | None = None
) -> None:
    session.add(
        SensorReading.from_state_dict(
            state_dict,
            source,
            simulation_run_id=simulation_run_id,
            origin=ORIGIN_SIMULATED,
            physics_version=PHYSICS_VERSION,
        )
    )
    await session.flush()


async def save_sensor_readings_bulk(
    session: AsyncSession, records: list[dict[str, Any]], source: str, simulation_run_id: int | None = None
) -> None:
    for record in records:
        session.add(
            SensorReading.from_state_dict(
                record,
                source,
                simulation_run_id=simulation_run_id,
                origin=ORIGIN_SIMULATED,
                physics_version=PHYSICS_VERSION,
            )
        )
    await session.flush()


async def save_simulation_run(
    session: AsyncSession, hours: int, utilisation: float, stress: float, result_snapshot: list[dict[str, Any]]
) -> SimulationRun:
    run = SimulationRun(
        hours=hours,
        utilisation=utilisation,
        stress=stress,
        result_snapshot=result_snapshot,
        physics_version=PHYSICS_VERSION,
    )
    session.add(run)
    await session.flush()
    return run


def _optimizer_model_version() -> Optional[str]:
    """Version of the newest ``ppo_optimizer`` registry entry, else None.

    Note: this is the newest *logged* training run; the registry does not record
    which artifact the running process actually loaded.
    """
    try:
        from src.model_registry import latest

        entry = latest("ppo_optimizer")
        return str(entry["version"]) if entry and entry.get("version") else None
    except Exception:
        return None


async def save_optimization_result(session: AsyncSession, **fields: Any) -> OptimizationResult:
    data = {**fields, "physics_version": PHYSICS_VERSION}
    if data.get("model_version") is None:
        data["model_version"] = _optimizer_model_version()
    opt = OptimizationResult(**data)
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
    alert.acknowledged_at = datetime.now(timezone.utc)
    await session.flush()
    return alert
