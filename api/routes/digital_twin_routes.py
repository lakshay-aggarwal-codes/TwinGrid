from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.repositories import data_repository
from api.serialization import to_jsonable
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
    result = to_jsonable(twin_service.compute_state(utilisation, outside_temp, water_stress, mode))
    await data_repository.save_sensor_reading(session, result, "api")
    return result


@router.get("/api/simulate/{hours}")
async def simulate(
    hours: Annotated[int, Path(ge=1, le=168, description="Hours to simulate (1-168)")],
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    utilisation: float = Query(0.7, ge=0, le=1),
    stress: float = Query(0.3, ge=0, le=1, description="Water stress"),
) -> list[dict[str, Any]]:
    """Simulate for N hours, returning hourly snapshots.

    ``hours`` outside 1-168 is rejected with 422 by request validation (it used
    to reach the service and surface as a 500). The simulation is CPU-bound, so
    it runs in a worker thread instead of blocking the event loop.
    """
    hourly = to_jsonable(await run_in_threadpool(twin_service.compute_simulation, hours, utilisation, stress))
    run = await data_repository.save_simulation_run(session, hours, utilisation, stress, hourly)
    await data_repository.save_sensor_readings_bulk(session, hourly, "simulation", simulation_run_id=run.id)
    return hourly


@router.get("/api/whatif")
async def whatif(
    _user: Annotated[User, Depends(get_current_user)],
    utilisation: float = Query(0.65, ge=0, le=1, description="Server utilisation [0-1]"),
    outside_temp: float = Query(22.0, ge=-10, le=50, description="Outside temp (°C)"),
    water_stress: float = Query(0.0, ge=0, le=1, description="Water stress [0-1]"),
    mode: Literal["auto", "free_air", "closed_loop", "evaporative", "hybrid"] = Query("auto"),
    chilled_water_temp: float = Query(7.0, ge=5, le=15, description="Chilled-water setpoint (°C)"),
) -> dict[str, Any]:
    """Run an isolated 24 h digital-twin scenario at constant inputs and return its
    aggregate PUE / WUE / water / energy / CO2. Nothing is persisted and the
    shared live twin is not touched."""
    result = await run_in_threadpool(
        twin_service.compute_whatif, utilisation, outside_temp, water_stress, mode, chilled_water_temp
    )
    return to_jsonable(result)
