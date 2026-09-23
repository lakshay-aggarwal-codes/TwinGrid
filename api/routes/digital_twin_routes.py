from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.repositories import data_repository
from api.serialization import serialize_timestamps, serialize_timestamps_bulk
from api.services import twin_service
from database import get_db
from models.db_models import User

router = APIRouter(tags=["digital-twin"])


@router.get("/api/state")
async def get_state(
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    utilisation: float = Query(0.5, ge=0, le=1, description="Server utilisation [0-1]"),
    outside_temp: float = Query(25.0, ge=-10, le=50, description="Outside temp (°C)"),
    water_stress: float = Query(0.0, ge=0, le=1, description="Water stress [0-1]"),
    mode: str = Query("auto", description="Cooling mode: auto, free_air, closed_loop, evaporative, hybrid"),
) -> dict[str, Any]:
    """Get current state after one step. If mode='auto', uses rule-based selection."""
    result = twin_service.compute_state(utilisation, outside_temp, water_stress, mode)
    await data_repository.save_sensor_reading(session, result, "api")
    return serialize_timestamps(result)


@router.get("/api/simulate/{hours}")
async def simulate(
    hours: int,
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    utilisation: float = Query(0.7, ge=0, le=1),
    stress: float = Query(0.3, ge=0, le=1, description="Water stress"),
) -> list[dict[str, Any]]:
    """Simulate for N hours, returning hourly snapshots."""
    hourly = twin_service.compute_simulation(hours, utilisation, stress)
    run = await data_repository.save_simulation_run(session, hours, utilisation, stress, hourly)
    await data_repository.save_sensor_readings_bulk(session, hourly, "simulation", simulation_run_id=run.id)
    return serialize_timestamps_bulk(hourly)