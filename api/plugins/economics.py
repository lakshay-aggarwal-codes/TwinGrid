"""Plugin: ``GET /api/economics/summary`` -- energy cost of a simulated 24 h scenario under an illustrative tariff (Task 25).

Read-only; nothing is persisted. The energy is the twin's own ``total_energy_kwh`` from the isolated 24 h what-if run
(constant inputs, so it is spread evenly over the 24 hours); the baseline is the backend's default what-if. Cost
arithmetic lives in ``src.economics.tariff``. Rate limit: ``RATE_LIMIT_ECONOMICS`` (default ``12/minute``, see
``docs/env/Task25.md``): each call is two 24 h twin runs, executed as ONE unit under the shared compute bound.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from api.auth import get_current_user
from api.rate_limit import limiter, run_compute
from api.serialization import to_jsonable
from api.services import scenario_registry as SR
from api.services import twin_service
from models.db_models import User
from src.economics import tariff as T

router = APIRouter(tags=["economics"])

DEFAULT_LIMIT = "12/minute"
BASIS = (
    "Cost of one simulated 24 h run at constant inputs. Energy is the twin's own total, spread evenly over the 24 hours; "
    "peak demand is that even hourly power (the run has no separate peak). Savings = baseline cost - scenario cost, "
    "where the baseline is the backend's default what-if."
)


def _limit() -> str:
    """Read on every request so a deployment or a test can change it without a reload."""
    return os.getenv("RATE_LIMIT_ECONOMICS", "").strip() or DEFAULT_LIMIT


def _side(tariff: T.Tariff, result: dict[str, Any]) -> dict[str, Any]:
    kwh = float(result["total_energy_kwh"])
    cost = T.daily_cost(tariff, T.flat_hourly_profile(kwh))
    return {"inputs": result["inputs"], "mean_pue": result["mean_pue"], "cost": asdict(cost)}


def compute_summary(
    tariff: T.Tariff,
    scenario_inputs: dict[str, Any],
    whatif: Callable[..., dict[str, Any]] = twin_service.compute_whatif,
) -> dict[str, Any]:
    """Blocking and CPU-bound (two 24 h twin runs): call through ``run_compute``."""
    tariff.validate()
    keys = ("utilisation", "outside_temp", "water_stress", "mode", "chilled_water_temp")
    base_inputs = {k: SR.WHATIF_DEFAULTS[k] for k in keys}
    base_run = whatif(*(base_inputs[k] for k in keys))
    scen_run = base_run if scenario_inputs == base_inputs else whatif(*(scenario_inputs[k] for k in keys))
    base = _side(tariff, base_run)
    scen = _side(tariff, scen_run)
    sav = T.savings(T.CostBreakdown(**base["cost"]), T.CostBreakdown(**scen["cost"]))
    return {
        "label": T.ILLUSTRATIVE_LABEL
        if tariff == T.DEFAULT_TARIFF
        else f"{T.ILLUSTRATIVE_LABEL} (user-entered rates, still not a quote)",
        "estimate_label": "model estimate on simulated data",
        "origin": "simulated",
        "basis": BASIS,
        "currency": tariff.currency,
        "currency_note": "Rates are taken to be in this currency. Nothing is converted.",
        "tariff": tariff.as_dict(),
        "is_default_tariff": tariff == T.DEFAULT_TARIFF,
        "scenario": scen,
        "baseline": base,
        "savings": asdict(sav),
        "carbon_data_is_real": bool(scen_run.get("carbon_data_is_real")),
    }


@router.get("/api/economics/summary")
@limiter.limit(_limit)
async def economics_summary(
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
    currency: str = Query(T.DEFAULT_TARIFF.currency, pattern=r"^[A-Za-z]{3}$"),
    off_peak_rate: float = Query(T.DEFAULT_TARIFF.off_peak_rate, ge=0, le=1000),
    peak_rate: float = Query(T.DEFAULT_TARIFF.peak_rate, ge=0, le=1000),
    peak_start_hour: int = Query(T.DEFAULT_TARIFF.peak_start_hour, ge=0, le=24),
    peak_end_hour: int = Query(T.DEFAULT_TARIFF.peak_end_hour, ge=0, le=24),
    demand_charge_per_kw: float = Query(T.DEFAULT_TARIFF.demand_charge_per_kw, ge=0, le=100000),
    billing_days: int = Query(T.DEFAULT_TARIFF.billing_days, ge=1, le=366),
) -> dict[str, Any]:
    """Cost of the scenario and of the default baseline under the given tariff, and the difference (model estimate on
    simulated data; the default tariff is labelled illustrative, not a quote). Same inputs, same answer."""
    tariff = T.Tariff(
        currency.upper(), off_peak_rate, peak_rate, peak_start_hour, peak_end_hour, demand_charge_per_kw, billing_days
    )
    scenario = {
        "utilisation": utilisation,
        "outside_temp": outside_temp,
        "water_stress": water_stress,
        "mode": mode,
        "chilled_water_temp": chilled_water_temp,
    }
    result = await run_compute(compute_summary, tariff, scenario)
    return to_jsonable(result)
