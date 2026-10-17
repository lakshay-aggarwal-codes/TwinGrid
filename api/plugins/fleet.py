"""Task 30 plugin: ``GET /api/fleet/sites``. Five SIMULATED sites (see ``src/fleet/sites.py``) run through the same
digital twin as ``/api/state`` (throwaway twin, ``live=False``), ranked by PUE, carbon and simulated alert conditions.
Read-only, any signed-in role. Nothing is stored and the live twin is never touched.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.rate_limit import http_limit
from api.serialization import to_jsonable
from api.services import twin_service
from models.db_models import User
from src.digital_twin import INLET_TEMP_MAX, INLET_TEMP_MIN, OUTLET_TEMP_MAX
from src.fleet.ranking import alert_conditions, rank_fleet
from src.fleet.sites import LABEL, SITES

router = APIRouter(tags=["fleet"])

CARBON_NOTE_FLAT = (
    "Carbon uses a flat assumed grid intensity (no carbon data file), so carbon differences between sites reflect "
    "energy use only, not different grids."
)
CARBON_NOTE_REAL = "Carbon uses the loaded intensity curve for the site time zone; all sites share that one curve."


def build_fleet() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    carbon_real = True
    for s in SITES:
        state = to_jsonable(
            twin_service.compute_state(s.utilisation, s.outside_temp_c, s.water_stress, "auto", live=False)
        )
        carbon_real = carbon_real and bool(state.get("carbon_data_is_real"))
        conds = alert_conditions(state, outlet_max=OUTLET_TEMP_MAX, inlet_min=INLET_TEMP_MIN, inlet_max=INLET_TEMP_MAX)
        rows.append(
            {
                "id": s.id,
                "name": s.name,
                "climate": s.climate,
                "inputs": {
                    "utilisation": s.utilisation,
                    "outside_temp_C": s.outside_temp_c,
                    "water_stress": s.water_stress,
                },
                "pue": state["pue"],
                "wue": state["wue"],
                "cooling_mode": state["cooling_mode"],
                "total_power_kw": state["total_power_kw"],
                "server_outlet_temp_C": state["server_outlet_temp_C"],
                "carbon_gco2_per_step": state["carbon_gco2"],
                "alert_conditions": len(conds),
                "alert_condition_names": conds,
            }
        )
    return {
        "simulated": True,
        "label": LABEL,
        "alert_note": "Alert conditions are rule checks on the simulated state, not recorded alerts.",
        "carbon_data_is_real": carbon_real,
        "carbon_note": CARBON_NOTE_REAL if carbon_real else CARBON_NOTE_FLAT,
        "carbon_unit": "gCO2 per 5-minute step",
        "sites": rank_fleet(rows),
    }


@router.get("/api/fleet/sites", dependencies=[Depends(http_limit("state"))])
async def get_fleet_sites(_user: Annotated[User, Depends(get_current_user)]) -> dict[str, Any]:
    """Five simulated sites with ranks by PUE, carbon and simulated alert conditions (lower is better)."""
    return build_fleet()
