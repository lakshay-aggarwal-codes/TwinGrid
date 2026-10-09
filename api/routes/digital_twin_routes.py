from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api import config
from api.auth import get_current_user
from api.rate_limit import http_limit, run_compute
from api.repositories import data_repository
from api.serialization import to_jsonable
from api.services import scenario_registry as SR
from api.services import twin_service
from database import get_db
from models.db_models import User
from src.facility_benchmarking import benchmark_pue

router = APIRouter(tags=["digital-twin"])


@router.get("/api/state", dependencies=[Depends(http_limit("state"))])
async def get_state(
    _user: Annotated[User, Depends(get_current_user)],
    utilisation: float = Query(0.5, ge=0, le=1, description="Server utilisation [0-1]"),
    outside_temp: float = Query(25.0, ge=-10, le=50, description="Outside temp (°C)"),
    water_stress: float = Query(0.0, ge=0, le=1, description="Water stress [0-1]"),
    mode: Literal["auto", "free_air", "closed_loop", "evaporative", "hybrid"] = Query(
        "auto", description="Cooling mode: auto, free_air, closed_loop, evaporative, hybrid"
    ),
) -> dict[str, Any]:
    """Stateless PREVIEW of one twin step for the given inputs. If mode='auto',
    uses rule-based selection.

    This is a what-the-twin-would-do-now calculation, not the live state (the
    live state is what the WebSocket broadcasts). It runs on a throwaway twin
    (``live=False``), so it does not advance the shared live twin, does not
    touch its clock/thermal state/cumulative counters, and persists nothing.
    Because the twin is fresh on every call, cumulative fields such as
    ``water_consumed_L`` reflect a single step, not the live accumulator.
    """
    return to_jsonable(twin_service.compute_state(utilisation, outside_temp, water_stress, mode, live=False))


@router.get("/api/benchmark", dependencies=[Depends(http_limit("benchmark"))])
async def get_benchmark(
    _user: Annotated[User, Depends(get_current_user)],
    utilisation: float = Query(0.5, ge=0, le=1),
    outside_temp: float = Query(25.0, ge=-10, le=50),
    water_stress: float = Query(0.0, ge=0, le=1),
) -> dict[str, Any]:
    """Current-state PUE classified against the Uptime Institute 2024
    industry survey (see src/facility_benchmarking.py) instead of an
    arbitrary hand-picked threshold."""
    state = to_jsonable(twin_service.compute_state(utilisation, outside_temp, water_stress, "auto", live=False))
    return benchmark_pue(state["pue"])


@router.get("/api/simulate/{hours}", dependencies=[Depends(http_limit("simulate"))])
async def simulate(
    hours: Annotated[int, Path(ge=1, le=168, description="Hours to simulate (1-168)")],
    user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    utilisation: float = Query(0.7, ge=0, le=1),
    outside_temp: float = Query(25.0, ge=-10, le=50, description="Mean outside temp (°C) for the run"),
    stress: float = Query(0.3, ge=0, le=1, description="Water stress"),
    persist: bool = Query(
        False,
        description="Store the run and its hourly readings (operator only, at most 168 rows). Default: write nothing.",
    ),
) -> list[dict[str, Any]]:
    """Simulate for N hours, returning hourly snapshots.

    ``hours`` outside 1-168 is rejected with 422 by request validation (it used
    to reach the service and surface as a 500). The simulation is CPU-bound, so
    it runs in a worker thread instead of blocking the event loop.

    ``utilisation``/``outside_temp`` are the run's means; compute_simulation
    builds a diurnal curve around each rather than holding them flat for the
    whole period.

    T14: this GET writes NOTHING by default. ``persist=true`` (operator only) stores one SimulationRun plus one
    SensorReading per simulated hour (<= 168 rows). Concurrency and time are bounded (api/rate_limit.py
    ``run_compute``): 429 when too many compute-heavy requests run, 504 on timeout.
    """
    if persist and not user.is_operator():
        # Checked BEFORE computing: a viewer must not be able to spend CPU on a request that is going to fail.
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Operator role required to persist a simulation")
    hourly = to_jsonable(await run_compute(twin_service.compute_simulation, hours, utilisation, outside_temp, stress))
    if persist:
        if len(hourly) > config.MAX_SIMULATE_PERSIST_ROWS:  # unreachable while hours <= 168; kept as a hard cap
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Too many rows to persist")
        run = await data_repository.save_simulation_run(session, hours, utilisation, stress, hourly)
        await data_repository.save_sensor_readings_bulk(session, hourly, "simulation", simulation_run_id=run.id)
    return hourly


@router.get("/api/whatif", dependencies=[Depends(http_limit("whatif"))])
async def whatif(
    _user: Annotated[User, Depends(get_current_user)],
    scenario_id: str | None = Query(
        None, description="Optional preset id from GET /api/scenarios; explicit parameters below override it"
    ),
    utilisation: float | None = Query(
        None, ge=SR.UTILISATION_BOUNDS[0], le=SR.UTILISATION_BOUNDS[1], description="Server utilisation [0-1]"
    ),
    outside_temp: float | None = Query(
        None, ge=SR.OUTSIDE_TEMP_BOUNDS[0], le=SR.OUTSIDE_TEMP_BOUNDS[1], description="Outside temp (°C)"
    ),
    water_stress: float | None = Query(
        None, ge=SR.WATER_STRESS_BOUNDS[0], le=SR.WATER_STRESS_BOUNDS[1], description="Water stress [0-1]"
    ),
    mode: Literal["auto", "free_air", "closed_loop", "evaporative", "hybrid"] | None = Query(None),
    chilled_water_temp: float | None = Query(
        None,
        ge=SR.CHILLED_WATER_TEMP_BOUNDS[0],
        le=SR.CHILLED_WATER_TEMP_BOUNDS[1],
        description="Chilled-water setpoint (°C)",
    ),
) -> dict[str, Any]:
    """Run an isolated 24 h digital-twin scenario at constant inputs and return its
    aggregate PUE / WUE / water / energy / CO2. Nothing is persisted and the
    shared live twin is not touched.

    Parameter precedence: explicit query value > ``scenario_id`` preset > built-in default
    (utilisation 0.65, outside_temp 22, water_stress 0, mode auto, chilled_water_temp 7). The response
    echoes ``scenario_id`` (null for a raw what-if) and the resolved ``inputs``. An unknown
    ``scenario_id`` is a 404, never silently ignored.
    """
    if scenario_id is not None and SR.get_scenario(scenario_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Unknown scenario_id: {scenario_id!r}")
    base = SR.scenario_defaults(scenario_id) if scenario_id is not None else dict(SR.WHATIF_DEFAULTS)
    given = {
        "utilisation": utilisation,
        "outside_temp": outside_temp,
        "water_stress": water_stress,
        "mode": mode,
        "chilled_water_temp": chilled_water_temp,
    }
    p = {k: (given[k] if given[k] is not None else base[k]) for k in base}
    result = await run_compute(
        twin_service.compute_whatif,
        p["utilisation"],
        p["outside_temp"],
        p["water_stress"],
        p["mode"],
        p["chilled_water_temp"],
    )
    return {**to_jsonable(result), "scenario_id": scenario_id}
