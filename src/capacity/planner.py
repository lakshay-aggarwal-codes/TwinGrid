"""Capacity headroom and the "add N racks at X kW" what-if (Task 26).

Everything here is a MODEL-BASED ESTIMATE on simulated data, not a measurement and not a design sign-off. There is no
per-rack or per-zone model in the backend: the twin describes the facility in aggregate, so headroom is a FACILITY
figure and nothing below is split per rack.

Limits (all taken from the twin itself, none invented here):
  * power    rated IT power of the modelled facility (``max_it_power_kw``) minus the IT power drawn;
  * cooling  the plant's heat-removal capacity at the scenario's outside temperature (the twin's own derated capacity,
             ``last_balance["capacity_kw"]``) minus the IT heat to remove; unmodelled (``None``) in physics legacy-0;
  * thermal  the safety envelope's outlet limit minus the highest server outlet temperature over the 24 h run
             (and, for information, the same for the inlet limit).

"Add N racks at X kW": the N x X kW is extra, constant IT load on the SAME cooling plant (capacity unchanged) and the
same air handling. The twin is run twice with identical inputs, once as is and once with the load added. The twin has no
"extra load" input, so the added load is expressed as a larger ``max_it_power_kw`` at the utilisation that yields
exactly base IT + N x X kW; the cooling capacity is pinned to the facility's design value. Above the rated IT power the
twin's airflow stays at its full-load value (the existing air handling is not enlarged).

PURE apart from the twin runs: no clock, no randomness, no I/O; the caller injects ``make_twin`` so a test can pass a
fake. Same inputs, same output.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping

from src.digital_twin import INLET_TEMP_MAX, OUTLET_TEMP_MAX, CoolingMode

LABEL = "model-based estimate"
BASIS = (
    "Steady 24 h run of the digital twin at constant inputs (simulated data). Headroom is a facility figure: the model "
    "has no per-rack or per-zone limits. Added racks are extra IT load on the existing cooling plant and air handling; "
    "the planning bands below are thresholds chosen for this model, not a standard."
)

HOURS = 24
STEPS_PER_HOUR = 12  # 5-minute twin steps, as everywhere else

MAX_ADD_RACKS = 200
KW_PER_RACK_BOUNDS = (0.1, 60.0)

# Planning bands (model choices, stated in BASIS): share of a limit, or degrees C of thermal margin, still free.
TIGHT_FRACTION = 0.10
TIGHT_MARGIN_C = 3.0

OK, TIGHT, EXCEEDED, UNKNOWN = "ok", "tight", "exceeded", "unknown"
FITS, FITS_TIGHT, DOES_NOT_FIT = "fits", "fits_with_little_margin", "does_not_fit"

MakeTwin = Callable[..., Any]


@dataclass(frozen=True)
class Scenario:
    utilisation: float
    outside_temp: float
    water_stress: float
    mode: str
    chilled_water_temp: float


@dataclass(frozen=True)
class Plan:
    add_racks: int
    kw_per_rack: float

    @property
    def added_kw(self) -> float:
        return self.add_racks * self.kw_per_rack

    def validate(self) -> "Plan":
        n = self.add_racks
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= MAX_ADD_RACKS:
            raise ValueError(f"add_racks must be an integer in [0, {MAX_ADD_RACKS}]")
        lo, hi = KW_PER_RACK_BOUNDS
        k = self.kw_per_rack
        if isinstance(k, bool) or not isinstance(k, (int, float)) or k != k or not lo <= k <= hi:
            raise ValueError(f"kw_per_rack must be a number in [{lo}, {hi}]")
        return self


# ------------------------------------------------------------------------------------------------ classification


def classify_share(headroom: float | None, limit: float | None) -> str:
    """ok / tight / exceeded for a power or cooling headroom against its limit; unknown when not modelled."""
    if headroom is None or limit is None or limit <= 0:
        return UNKNOWN
    if headroom < 0:
        return EXCEEDED
    return TIGHT if headroom < TIGHT_FRACTION * limit else OK


def classify_margin(margin_c: float) -> str:
    if margin_c != margin_c or margin_c < 0:  # NaN counts as exceeded, like the safety envelope
        return EXCEEDED
    return TIGHT if margin_c < TIGHT_MARGIN_C else OK


def overall_status(statuses: list[str]) -> str:
    """Worst of the known statuses (unknown never improves or worsens the result)."""
    known = [s for s in statuses if s != UNKNOWN]
    if EXCEEDED in known:
        return EXCEEDED
    return TIGHT if TIGHT in known else OK


def verdict_for(status: str) -> str:
    return {OK: FITS, TIGHT: FITS_TIGHT, EXCEEDED: DOES_NOT_FIT}[status]


# ------------------------------------------------------------------------------------------------ twin runs


def _ratings(twin: Any) -> tuple[float, float, float]:
    """(rated IT kW, design cooling capacity kW, idle power fraction) of a twin.

    Read from the twin's own attributes: there is no public accessor, and the numbers must be the twin's, not copies."""
    return float(twin._max_it_power_kw), float(twin._cooling_capacity_design_kw), float(twin._idle_power_fraction)


def _run(twin: Any, s: Scenario, utilisation: float) -> dict[str, float | None]:
    max_outlet = float("-inf")
    max_inlet = float("-inf")
    unremoved = 0.0
    last = None
    for _ in range(HOURS * STEPS_PER_HOUR):
        mode = twin.select_cooling_mode(s.outside_temp, s.water_stress) if s.mode == "auto" else CoolingMode(s.mode)
        last = twin.step(
            {
                "utilisation": utilisation,
                "outside_temp_C": s.outside_temp,
                "water_stress": s.water_stress,
                "cooling_mode": mode,
                "chilled_water_temp_C": s.chilled_water_temp,
            }
        )
        max_outlet = max(max_outlet, last.server_outlet_temp_C)
        max_inlet = max(max_inlet, last.server_inlet_temp_C)
        unremoved = max(unremoved, float(twin.last_balance.get("heat_unremoved_kw", 0.0)))
    bal = twin.last_balance
    capacity = bal.get("capacity_kw")
    capacity = float(capacity) if capacity is not None and capacity == capacity and capacity != float("inf") else None
    return {
        "it_power_kw": float(last.it_power_kw),
        "cooling_power_kw": float(last.cooling_power_kw),
        "total_power_kw": float(last.total_power_kw),
        "pue": float(last.pue),
        "max_inlet_temp_C": float(max_inlet),
        "max_outlet_temp_C": float(max_outlet),
        "cooling_capacity_kw": capacity,
        "max_heat_unremoved_kw": float(unremoved),
        "cooling_mode": last.cooling_mode.value,
    }


def _headroom(run: Mapping[str, Any], rated_it_kw: float) -> dict[str, Any]:
    cap = run["cooling_capacity_kw"]
    cool_head = None if cap is None else cap - run["it_power_kw"]
    power_head = rated_it_kw - run["it_power_kw"]
    thermal = OUTLET_TEMP_MAX - run["max_outlet_temp_C"]
    inlet = INLET_TEMP_MAX - run["max_inlet_temp_C"]
    cool_status = classify_share(cool_head, cap)
    if run["max_heat_unremoved_kw"] > 0:  # the twin itself reports heat the plant could not remove
        cool_status = EXCEEDED
    statuses = {
        "power": classify_share(power_head, rated_it_kw),
        "cooling": cool_status,
        "thermal": classify_margin(thermal),
    }
    return {
        "power_headroom_kw": power_head,
        "power_limit_kw": rated_it_kw,
        "cooling_headroom_kw": cool_head,
        "cooling_capacity_kw": cap,
        "thermal_margin_C": thermal,
        "inlet_margin_C": inlet,
        "status": statuses,
        "overall": overall_status(list(statuses.values())),
    }


def racks_that_fit(headroom_kw: float | None, kw_per_rack: float) -> int | None:
    """Whole racks of ``kw_per_rack`` that fit in a kW headroom (0 when there is none); None when not modelled."""
    if headroom_kw is None:
        return None
    return max(0, int(headroom_kw // kw_per_rack))


def evaluate(make_twin: MakeTwin, scenario: Scenario, plan: Plan) -> dict[str, Any]:
    """Headroom now, headroom with ``plan`` added, and the verdict. Blocking and CPU-bound: two 24 h twin runs."""
    plan.validate()
    base_twin = make_twin(initial_chilled_water_temp_C=scenario.chilled_water_temp)
    rated, design_cooling, idle = _ratings(base_twin)
    base_run = _run(base_twin, scenario, scenario.utilisation)
    base = {**base_run, **_headroom(base_run, rated)}

    target_it = base_run["it_power_kw"] + plan.added_kw
    if plan.add_racks == 0:
        cand_run, cand_rated = base_run, rated
    else:
        # Extra load expressed through the twin's own inputs (see module docstring). Cooling capacity stays as designed.
        big = max(rated, target_it)
        util = min(1.0, max(0.0, (target_it / big - idle) / (1.0 - idle))) if idle < 1.0 else 1.0
        cand_twin = make_twin(
            initial_chilled_water_temp_C=scenario.chilled_water_temp,
            max_it_power_kw=big,
            cooling_capacity_kw=design_cooling,
        )
        cand_run = _run(cand_twin, scenario, util)
        cand_rated = rated  # the electrical limit does not grow with the added racks
    cand = {**cand_run, **_headroom(cand_run, cand_rated)}

    by_power = racks_that_fit(base["power_headroom_kw"], plan.kw_per_rack)
    by_cooling = racks_that_fit(base["cooling_headroom_kw"], plan.kw_per_rack)
    known = [n for n in (by_power, by_cooling) if n is not None]
    return {
        "label": LABEL,
        "origin": "simulated",
        "basis": BASIS,
        "hours": HOURS,
        "limits_note": "Power and cooling headroom are facility totals (no per-rack or per-zone limits in the model). "
        "Thermal margin is to the safety envelope's outlet limit.",
        "bands": {"tight_fraction": TIGHT_FRACTION, "tight_margin_C": TIGHT_MARGIN_C},
        "scenario": asdict(scenario),
        "plan": {"add_racks": plan.add_racks, "kw_per_rack": plan.kw_per_rack, "added_kw": plan.added_kw},
        "baseline": base,
        "with_plan": cand,
        "verdict": verdict_for(cand["overall"]),
        "racks_that_fit": {
            "by_power": by_power,
            "by_cooling": by_cooling,
            "limit": min(known) if known else None,
            "note": "Power and cooling only; thermal margin is checked for the requested plan, not searched.",
        },
    }
