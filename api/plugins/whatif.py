"""Plugin: ``GET /api/whatif/sensitivity`` -- bounded, deterministic one-at-a-time sensitivity sweep (Task 15).

Read-only (ADR 007: nothing is persisted; this route has no ``persist`` option at all). Every run is the existing
isolated what-if computation; the sweep is capped at ``src.whatif_sweep.MAX_SWEEP_RUNS`` runs and executes as ONE
unit under the shared compute bound and timeout (``api.rate_limit.run_compute``). Rate limit: ``RATE_LIMIT_WHATIF_SWEEP``
(default ``6/minute``, see ``docs/env/Task15.md``), on the same limiter as the core routes.
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from api.auth import get_current_user
from api.rate_limit import limiter, run_compute
from api.serialization import to_jsonable
from api.services import scenario_registry as SR
from api.services import twin_service
from models.db_models import User
from src import whatif_sweep
from src.digital_twin import OUTLET_TEMP_MAX

router = APIRouter(tags=["digital-twin"])

DEFAULT_LIMIT = "6/minute"

BOUNDS = {
    "utilisation": SR.UTILISATION_BOUNDS,
    "outside_temp": SR.OUTSIDE_TEMP_BOUNDS,
    "water_stress": SR.WATER_STRESS_BOUNDS,
    "chilled_water_temp": SR.CHILLED_WATER_TEMP_BOUNDS,
}


def _limit() -> str:
    """Read on every request so a deployment or a test can change it without a reload."""
    return os.getenv("RATE_LIMIT_WHATIF_SWEEP", "").strip() or DEFAULT_LIMIT


def compute_sweep(
    utilisation: float, outside_temp: float, water_stress: float, mode: str, chilled_water_temp: float
) -> dict[str, Any]:
    """Blocking and CPU-bound (about a dozen 24 h twin runs): call through ``run_compute``."""
    base = {
        "utilisation": utilisation,
        "outside_temp": outside_temp,
        "water_stress": water_stress,
        "mode": mode,
        "chilled_water_temp": chilled_water_temp,
    }
    return whatif_sweep.run_sweep(base, twin_service.compute_whatif, BOUNDS, OUTLET_TEMP_MAX)


@router.get("/api/whatif/sensitivity")
@limiter.limit(_limit)
async def whatif_sensitivity(
    request: Request,
    response: Response,
    _user: Annotated[User, Depends(get_current_user)],
    utilisation: float = Query(
        SR.WHATIF_DEFAULTS["utilisation"], ge=SR.UTILISATION_BOUNDS[0], le=SR.UTILISATION_BOUNDS[1]
    ),
    outside_temp: float = Query(
        SR.WHATIF_DEFAULTS["outside_temp"], ge=SR.OUTSIDE_TEMP_BOUNDS[0], le=SR.OUTSIDE_TEMP_BOUNDS[1]
    ),
    water_stress: float = Query(
        SR.WHATIF_DEFAULTS["water_stress"], ge=SR.WATER_STRESS_BOUNDS[0], le=SR.WATER_STRESS_BOUNDS[1]
    ),
    mode: Literal["auto", "free_air", "closed_loop", "evaporative", "hybrid"] = Query(SR.WHATIF_DEFAULTS["mode"]),
    chilled_water_temp: float = Query(
        SR.WHATIF_DEFAULTS["chilled_water_temp"], ge=SR.CHILLED_WATER_TEMP_BOUNDS[0], le=SR.CHILLED_WATER_TEMP_BOUNDS[1]
    ),
) -> dict[str, Any]:
    """One-at-a-time sensitivity of PUE, energy, CO2 and thermal margin around the given inputs (model estimate on
    simulated data). Same inputs, same answer; at most ``max_runs`` twin runs per call."""
    result = await run_compute(compute_sweep, utilisation, outside_temp, water_stress, mode, chilled_water_temp)
    return to_jsonable(result)
