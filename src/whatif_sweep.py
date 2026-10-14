"""Bounded, deterministic one-at-a-time sensitivity sweep around one what-if scenario (Task 15).

PURE: no FastAPI, no I/O, no clock, no randomness. The caller supplies ``run`` (the existing isolated 24 h what-if
computation, ``api.services.twin_service.compute_whatif``), so every number returned is that function's own output;
this module only chooses which scenarios to run and subtracts the baseline from each.

Bounds (hard, constant, not request-controlled):

* at most ``MAX_SWEEP_RUNS`` runs per sweep (baseline + 2 per numeric parameter + one per alternative cooling mode =
  11 at most; a numeric side that would equal the baseline after clamping to the allowed range is not run);
* the sweep is a function of the base inputs only: the same inputs give identical output, run order and values.

Everything returned is a model estimate on simulated data (``LABEL``), never a measurement or a forecast.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

LABEL = "model estimate on simulated data"
BASIS = (
    "One-at-a-time sweep: each input is moved alone, the others stay at the baseline; every run is the same 24 h "
    "constant-input isolated twin run as /api/whatif. Interactions between inputs are not captured."
)

MAX_SWEEP_RUNS = 12
MODES: tuple[str, ...] = ("auto", "free_air", "closed_loop", "evaporative", "hybrid")

# (input name, label, unit, fixed step either side). Steps are constants so the sweep never depends on the caller.
NUMERIC_INPUTS: tuple[tuple[str, str, str | None, float], ...] = (
    ("utilisation", "Server utilisation (fraction of capacity)", None, 0.10),
    ("outside_temp", "Outside temperature", "°C", 5.0),
    ("chilled_water_temp", "Chilled-water setpoint", "°C", 2.0),
)
# What the twin computes per run (names as in the what-if response) plus the derived margin below.
METRICS: tuple[str, ...] = ("mean_pue", "total_energy_kwh", "total_co2_kg", "max_outlet_temp_C", "thermal_margin_C")

RunFn = Callable[[float, float, float, str, float], Mapping[str, Any]]


@dataclass(frozen=True)
class Case:
    parameter: str
    direction: str  # "low" | "high" | "alternative"
    value: float | str
    inputs: tuple[float, float, float, str, float]  # utilisation, outside_temp, water_stress, mode, chilled_water_temp


def _check(base: Mapping[str, Any], bounds: Mapping[str, tuple[float, float]]) -> None:
    if base["mode"] not in MODES:
        raise ValueError(f"unknown cooling mode {base['mode']!r}")
    for name in ("utilisation", "outside_temp", "water_stress", "chilled_water_temp"):
        lo, hi = bounds[name]
        v = base[name]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v != v or not (lo <= v <= hi):
            raise ValueError(f"{name} must be a number in [{lo}, {hi}]")


def plan_sweep(base: Mapping[str, Any], bounds: Mapping[str, tuple[float, float]]) -> list[Case]:
    """The cases to run AFTER the baseline, in a fixed order (inputs in ``NUMERIC_INPUTS`` order, low before high,
    then the other cooling modes in ``MODES`` order). Raises ``ValueError`` for a base outside ``bounds``."""
    _check(base, bounds)
    cases: list[Case] = []

    def inputs_with(**over: Any) -> tuple[float, float, float, str, float]:
        p = {**base, **over}
        return (
            float(p["utilisation"]),
            float(p["outside_temp"]),
            float(p["water_stress"]),
            str(p["mode"]),
            float(p["chilled_water_temp"]),
        )

    for name, _label, _unit, step in NUMERIC_INPUTS:
        lo, hi = bounds[name]
        b = float(base[name])
        for direction, v in (("low", max(lo, b - step)), ("high", min(hi, b + step))):
            v = round(float(v), 6)
            if v != round(b, 6):  # clamped onto the baseline: nothing new to run
                cases.append(Case(name, direction, v, inputs_with(**{name: v})))
    for mode in MODES:
        if mode != base["mode"]:
            cases.append(Case("mode", "alternative", mode, inputs_with(mode=mode)))
    if len(cases) + 1 > MAX_SWEEP_RUNS:  # cannot happen with the constants above; a hard stop if they are ever edited
        raise ValueError("sweep would exceed MAX_SWEEP_RUNS")
    return cases


def _metrics(result: Mapping[str, Any], outlet_limit_c: float) -> dict[str, float]:
    out = {k: float(result[k]) for k in ("mean_pue", "total_energy_kwh", "total_co2_kg", "max_outlet_temp_C")}
    out["thermal_margin_C"] = float(outlet_limit_c) - out["max_outlet_temp_C"]
    return out


def run_sweep(
    base: Mapping[str, Any],
    run: RunFn,
    bounds: Mapping[str, tuple[float, float]],
    outlet_limit_c: float,
) -> dict[str, Any]:
    """Run the baseline and every planned case, and return metrics plus ``variant - baseline`` deltas."""
    cases = plan_sweep(base, bounds)
    b_inputs = (
        float(base["utilisation"]),
        float(base["outside_temp"]),
        float(base["water_stress"]),
        str(base["mode"]),
        float(base["chilled_water_temp"]),
    )
    baseline_raw = run(*b_inputs)
    baseline = _metrics(baseline_raw, outlet_limit_c)

    by_param: dict[str, dict[str, Any]] = {}
    for name, label, unit, _step in NUMERIC_INPUTS:
        by_param[name] = {"parameter": name, "label": label, "unit": unit, "base": float(base[name]), "variants": []}
    by_param["mode"] = {
        "parameter": "mode",
        "label": "Cooling mode",
        "unit": None,
        "base": str(base["mode"]),
        "variants": [],
    }

    for case in cases:
        m = _metrics(run(*case.inputs), outlet_limit_c)
        by_param[case.parameter]["variants"].append(
            {
                "direction": case.direction,
                "value": case.value,
                "metrics": m,
                "deltas": {k: m[k] - baseline[k] for k in METRICS},
            }
        )
    return {
        "label": LABEL,
        "basis": BASIS,
        "runs": len(cases) + 1,
        "max_runs": MAX_SWEEP_RUNS,
        "inputs": {
            "utilisation": b_inputs[0],
            "outside_temp_C": b_inputs[1],
            "water_stress": b_inputs[2],
            "mode": b_inputs[3],
            "chilled_water_temp_C": b_inputs[4],
        },
        "outlet_limit_C": float(outlet_limit_c),
        "carbon_data_is_real": bool(baseline_raw.get("carbon_data_is_real", False)),
        "baseline": baseline,
        "parameters": [p for p in by_param.values() if p["variants"]],
    }
