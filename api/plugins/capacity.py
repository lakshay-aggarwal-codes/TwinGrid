"""Plugin: ``GET /api/capacity/headroom`` -- facility headroom and the "add N racks at X kW" what-if (Task 26).

Read-only; nothing is persisted. Every number is the digital twin's own output (two isolated 24 h runs at constant
inputs); the arithmetic and the labelling live in ``src.capacity.planner``. The answer is a model-based estimate on
simulated data. Rate limit: ``RATE_LIMIT_CAPACITY`` (default ``12/minute``, see ``docs/env/Task26.md``): each call is
two 24 h twin runs executed as ONE unit under the shared compute bound.
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from api.auth import get_current_user
from api.rate_limit import limiter, run_compute
from api.serialization import to_jsonable
from api.services import scenario_registry as SR
from models.db_models import User
from src.capacity import planner as P
from src.digital_twin import DigitalTwin

router = APIRouter(tags=["capacity"])

DEFAULT_LIMIT = "12/minute"


def _limit() -> str:
    """Read on every request so a deployment or a test can change it without a reload."""
    return os.getenv("RATE_LIMIT_CAPACITY", "").strip() or DEFAULT_LIMIT


def compute_headroom(scenario: P.Scenario, plan: P.Plan, make_twin=DigitalTwin) -> dict[str, Any]:
    """Blocking and CPU-bound (two 24 h twin runs): call through ``run_compute``."""
    return P.evaluate(make_twin, scenario, plan)


@router.get("/api/capacity/headroom")
@limiter.limit(_limit)
async def capacity_headroom(
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
    add_racks: int = Query(0, ge=0, le=P.MAX_ADD_RACKS),
    kw_per_rack: float = Query(8.0, ge=P.KW_PER_RACK_BOUNDS[0], le=P.KW_PER_RACK_BOUNDS[1]),
) -> dict[str, Any]:
    """Power, cooling and thermal headroom of the modelled facility now, and with ``add_racks`` racks of
    ``kw_per_rack`` kW added (model-based estimate on simulated data). Same inputs, same answer."""
    scenario = P.Scenario(utilisation, outside_temp, water_stress, mode, chilled_water_temp)
    result = await run_compute(compute_headroom, scenario, P.Plan(add_racks, kw_per_rack))
    return to_jsonable(result)
