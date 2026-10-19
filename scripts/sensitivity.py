#!/usr/bin/env python3
"""Physics sensitivity study (Task 10): which documented physics parameters do the baseline results depend on?

    python scripts/sensitivity.py                         # both studies, Markdown tables on stdout
    python scripts/sensitivity.py --format json --out sensitivity.json
    python scripts/sensitivity.py --scenarios-per-family 1 --studies physics1     # quick run

THIS IS NOT CALIBRATION. It perturbs each documented parameter one at a time by -25 %, -10 %, +10 %, +25 % of its
default and reports how far a few metrics move. It says nothing about which value is RIGHT, and every number comes from
the SIMULATOR (synthetic diurnal workload and weather, uncalibrated parameters).

Study 1 -- physics 1 through the repo's own harness (``src.policy_evaluation.run_episode``, frozen). Four baselines:
the production rule and three constant set-points (low / middle / high of physics 1's actuator range) in closed-loop
mode. A parameter is perturbed by temporarily changing the physics module's own constant (and restoring it), so no
physics file is edited. Scenarios are VALIDATION-split scenarios of the shipped protocol (never the held-out test
split), the first ``--scenarios-per-family`` of each family, in protocol order.

Study 2 -- physics 2, the TWIN ONLY (the RL environment refuses physics 2, ``UnsupportedPhysicsVersionForRL``). The
exogenous trace (utilisation, outside temperature, water stress per step) of every Study 1 scenario is replayed
OPEN LOOP into ``DigitalTwin(physics_version="2")`` under the same four control rules, with every numeric field of
``PhysicsParams`` perturbed in turn. There is no safety shield and no observation feedback in this replay.

Metrics per policy, averaged over the scenarios: mean PUE, energy (kWh per episode), water (L), mean and max server
outlet and inlet temperature (C), and the number of steps that violate THE safety envelope (``SAFETY_ENVELOPE``:
inlet, outlet, PUE), by limit. The envelope limits themselves are never perturbed.

Determinism: no clock, no random generator. Same code and same inputs give the same numbers; ``results_sha256`` in the
output is a hash of the rounded numbers, for comparing two machines (it can differ in the last digits across
platforms; compare the tables first).
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import math
import platform
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from src import digital_twin as dt  # noqa: E402
from src.digital_twin import CoolingMode, DigitalTwin, InvalidInputError  # noqa: E402
from src.physics.params import PhysicsParams, PhysicsParamsError  # noqa: E402
from src.physics.v2 import PhysicsStabilityError  # noqa: E402

SCHEMA = "twingrid-sensitivity/1"
FACTORS: tuple[float, ...] = (0.75, 0.90, 1.10, 1.25)
LEVEL_LABELS: tuple[str, ...] = ("-25%", "-10%", "+10%", "+25%")
CONSTANT_MODE = "closed_loop"
REPORT_ROUND = 9  # decimals kept in the JSON / hash

# Documented parameters of physics 1 that are literals inside the equations, not constants: they cannot be perturbed
# without editing the physics file, which this study does not do. (In physics 2 they are PhysicsParams fields and are
# covered by Study 2.)
V1_LITERALS: dict[str, str] = {
    "cop_outside_derate_start_c": "the 20.0 inside DigitalTwin._effective_cop",
    "cop_chw_bonus_floor": "the 0.5 floor inside DigitalTwin._effective_cop",
    "water_warm_reference_c": "the 15.0 inside DigitalTwin._water_consumption_v1",
}
# PhysicsParams fields that exist only in physics 2 (no physics-1 counterpart): covered by Study 2 only.
V2_ONLY: tuple[str, ...] = (
    "thermal_capacitance_kj_per_k",
    "coil_ua_kw_per_k",
    "max_dt_over_tau",
    "tau_chw_min",
    "capacity_design_kw",
    "humidity_reference_pct",
    "wet_bulb_factor_min",
    "wet_bulb_factor_max",
)

# ----------------------------------------------------------------------------- parameter registry (physics 1)


@dataclass(frozen=True)
class Param:
    """One physics-1 parameter: its documented name (docs/PHYSICS_V2.md, the PhysicsParams field), where it lives in
    the code, and how to read and write it. ``doc_scale``: documented value = ``doc_scale`` x code value."""

    name: str
    group: str
    where: str
    get: Callable[[], float]
    put: Callable[[float], None]
    doc_scale: float = 1.0

    def base(self) -> float:
        return float(self.get())

    def documented_value(self) -> float:
        return self.doc_scale * self.base()


def _env() -> Any:
    from src.rl import env  # needs gymnasium; imported only when a physics-1 value is read

    return env


Access = tuple[Callable[[], float], Callable[[float], None], str]  # (get, put, where it lives in the code)


def _module_attr(module: Callable[[], Any], attr: str, label: str) -> Access:
    return (lambda: getattr(module(), attr)), (lambda v: setattr(module(), attr, v)), label


def _dict_entry(module: Callable[[], Any], table: str, key: Any, label: str) -> Access:
    return (lambda: getattr(module(), table)[key]), (lambda v: getattr(module(), table).__setitem__(key, v)), label


def _kwdefault(key: str, label: str) -> Access:
    # DigitalTwin.__init__ takes these keyword-only: their defaults live in __kwdefaults__ and are read at call time.
    return (
        (lambda: DigitalTwin.__init__.__kwdefaults__[key]),  # type: ignore[index]
        (lambda v: DigitalTwin.__init__.__kwdefaults__.__setitem__(key, v)),  # type: ignore[union-attr]
        label,
    )


def _latent_heat() -> Access:
    def put(value: float) -> None:
        dt.LATENT_HEAT_VAPORISATION_J_PER_KG = value
        # The module derives its water bound from the latent heat once, at import; recompute it the same way.
        dt.LATENT_WATER_BOUND_L_PER_KWH = dt.JOULES_PER_KWH / (value * dt.WATER_DENSITY_KG_PER_L)

    where = "digital_twin.LATENT_HEAT_VAPORISATION_J_PER_KG (and the derived LATENT_WATER_BOUND_L_PER_KWH)"
    return (lambda: dt.LATENT_HEAT_VAPORISATION_J_PER_KG), put, where


def _dtm() -> Any:
    return dt


def registry_v1() -> list[Param]:
    """The physics-1 parameters of docs/PHYSICS_V2.md marked (v1), in the document's order. Resolved lazily: the
    environment constants need gymnasium, which only Study 1 and the tests that use them import."""
    M = CoolingMode
    # fmt: off
    rows: list[tuple[str, str, Access, float]] = [
        ("max_it_power_kw", "IT load", _module_attr(_env, "MAX_IT_POWER_KW", "rl.env.MAX_IT_POWER_KW (passed to the twin on every reset)"), 1.0),
        ("idle_power_fraction", "IT load", _module_attr(_env, "IDLE_FRAC", "rl.env.IDLE_FRAC"), 1.0),
        ("air_flow_base_m3_s", "Air path", _module_attr(_env, "AIRFLOW_M3_S", "rl.env.AIRFLOW_M3_S"), 1.0),
        ("air_flow_full_load_m3_s", "Air path", _module_attr(_dtm, "AIR_FLOW_FULL_LOAD_M3_S", "digital_twin.AIR_FLOW_FULL_LOAD_M3_S"), 1.0),
        ("tau_air_min", "Air path", _kwdefault("thermal_time_constant_min", "DigitalTwin.__init__ default thermal_time_constant_min"), 1.0),
        ("chw_approach_c", "Air path", _module_attr(_dtm, "CHILLED_WATER_APPROACH_C", "digital_twin.CHILLED_WATER_APPROACH_C"), 1.0),
        ("inlet_supply_floor_c", "Air path", _module_attr(_dtm, "INLET_SUPPLY_FLOOR_C", "digital_twin.INLET_SUPPLY_FLOOR_C (the plant's supply-air floor, NOT the envelope limit)"), 1.0),
        ("free_air_fan_heat_c", "Air path", _module_attr(_dtm, "FREE_AIR_FAN_HEAT_C", "digital_twin.FREE_AIR_FAN_HEAT_C"), 1.0),
        ("free_air_ineffective_above_c", "Air path", _module_attr(_dtm, "FREE_AIR_INEFFECTIVE_OUTSIDE_TEMP_C", "digital_twin.FREE_AIR_INEFFECTIVE_OUTSIDE_TEMP_C"), 1.0),
        ("chw_rate_limit_c_per_5min", "Actuator", _kwdefault("max_chilled_water_rate_C_per_step", "DigitalTwin.__init__ default max_chilled_water_rate_C_per_step"), 1.0),
        ("capacity_margin", "Capacity", _module_attr(_dtm, "COOLING_CAPACITY_MARGIN", "digital_twin.COOLING_CAPACITY_MARGIN"), 1.0),
        ("capacity_derate_start_c", "Capacity", _module_attr(_dtm, "CAPACITY_DERATE_START_OUTSIDE_C", "digital_twin.CAPACITY_DERATE_START_OUTSIDE_C"), 1.0),
        ("capacity_derate_per_c", "Capacity", _module_attr(_dtm, "CAPACITY_DERATE_PER_C", "digital_twin.CAPACITY_DERATE_PER_C"), 1.0),
        ("capacity_min_fraction", "Capacity", _module_attr(_dtm, "CAPACITY_MIN_FRACTION", "digital_twin.CAPACITY_MIN_FRACTION"), 1.0),
        ("cop_free_air", "COP", _dict_entry(_dtm, "_BASE_COP", M.FREE_AIR, "digital_twin._BASE_COP[free_air]"), 1.0),
        ("cop_closed_loop", "COP", _dict_entry(_dtm, "_BASE_COP", M.CLOSED_LOOP, "digital_twin._BASE_COP[closed_loop]"), 1.0),
        ("cop_evaporative", "COP", _dict_entry(_dtm, "_BASE_COP", M.EVAPORATIVE, "digital_twin._BASE_COP[evaporative]"), 1.0),
        ("cop_hybrid", "COP", _dict_entry(_dtm, "_BASE_COP", M.HYBRID, "digital_twin._BASE_COP[hybrid]"), 1.0),
        ("cop_load_derate", "COP", _module_attr(_dtm, "COP_LOAD_DERATE", "digital_twin.COP_LOAD_DERATE"), 1.0),
        ("cop_outside_derate_per_c", "COP", _module_attr(_dtm, "COP_OUTSIDE_TEMP_DERATE_PER_C", "digital_twin.COP_OUTSIDE_TEMP_DERATE_PER_C"), 1.0),
        ("cop_min", "COP", _module_attr(_dtm, "COP_MIN", "digital_twin.COP_MIN"), 1.0),
        ("cop_chw_reference_c", "COP", _module_attr(_dtm, "DEFAULT_CHILLED_WATER_TEMP_C", "digital_twin.DEFAULT_CHILLED_WATER_TEMP_C (the COP reference set-point)"), 1.0),
        ("cop_chw_lift_per_c", "COP", _module_attr(_dtm, "COP_CHILLED_WATER_LIFT_DERATE_PER_C", "digital_twin.COP_CHILLED_WATER_LIFT_DERATE_PER_C"), 1.0),
        ("cop_humidity_reference_pct", "COP", _module_attr(_dtm, "EVAPORATIVE_HUMIDITY_REFERENCE_PCT", "digital_twin.EVAPORATIVE_HUMIDITY_REFERENCE_PCT"), 1.0),
        # Physics 1 stores ONE humidity constant (0.01); the evaporative COP derate is half of it (0.5 x ...) = 0.005.
        ("cop_humidity_derate_per_pct", "COP", _module_attr(_dtm, "WATER_HUMIDITY_FACTOR_PER_PCT", "digital_twin.WATER_HUMIDITY_FACTOR_PER_PCT (the COP derate is 0.5 x this)"), 0.5),
        ("latent_heat_j_per_kg", "Water", _latent_heat(), 1.0),
        ("evap_fraction_free_air", "Water", _dict_entry(_dtm, "_EVAPORATIVE_HEAT_FRACTION", M.FREE_AIR, "digital_twin._EVAPORATIVE_HEAT_FRACTION[free_air]"), 1.0),
        ("evap_fraction_closed_loop", "Water", _dict_entry(_dtm, "_EVAPORATIVE_HEAT_FRACTION", M.CLOSED_LOOP, "digital_twin._EVAPORATIVE_HEAT_FRACTION[closed_loop]"), 1.0),
        ("evap_fraction_evaporative", "Water", _dict_entry(_dtm, "_EVAPORATIVE_HEAT_FRACTION", M.EVAPORATIVE, "digital_twin._EVAPORATIVE_HEAT_FRACTION[evaporative]"), 1.0),
        ("evap_fraction_hybrid", "Water", _dict_entry(_dtm, "_EVAPORATIVE_HEAT_FRACTION", M.HYBRID, "digital_twin._EVAPORATIVE_HEAT_FRACTION[hybrid]"), 1.0),
        ("water_warm_factor_per_c", "Water", _module_attr(_dtm, "WATER_TEMP_FACTOR_PER_C", "digital_twin.WATER_TEMP_FACTOR_PER_C"), 1.0),
    ]
    # fmt: on
    return [Param(n, g, where, get, put, scale) for n, g, (get, put, where), scale in rows]


@contextlib.contextmanager
def perturbed(param: Param, factor: float) -> Iterator[float]:
    """Set ``param`` to ``factor`` x its current value for the duration of the block, then restore it exactly (also
    when the block raises). Yields the perturbed value."""
    base = param.base()
    try:
        param.put(base * factor)
        yield base * factor
    finally:
        param.put(base)


# ----------------------------------------------------------------------------- metrics


METRICS: tuple[str, ...] = (
    "mean_pue",
    "energy_kwh",
    "water_L",
    "mean_outlet_C",
    "max_outlet_C",
    "mean_inlet_C",
    "max_inlet_C",
    "violation_steps",
    "outlet_above_max_steps",
    "inlet_above_max_steps",
    "inlet_below_min_steps",
    "pue_above_max_steps",
)


class _Acc:
    """Accumulates one episode from per-step state dicts (the environment's state, or the twin's state)."""

    def __init__(self) -> None:
        self.pue: list[float] = []
        self.outlet: list[float] = []
        self.inlet: list[float] = []
        self.energy_kwh = 0.0
        self.water_L = 0.0
        self.counts = {
            "violation_steps": 0,
            "outlet_above_max_steps": 0,
            "inlet_above_max_steps": 0,
            "inlet_below_min_steps": 0,
            "pue_above_max_steps": 0,
        }

    def add(self, inlet: float, outlet: float, pue: float, total_kw: float, water_L: float, dt_h: float) -> None:
        self.pue.append(pue)
        self.outlet.append(outlet)
        self.inlet.append(inlet)
        self.energy_kwh += total_kw * dt_h
        self.water_L += water_L
        found = dt.SAFETY_ENVELOPE.violations(inlet, outlet, pue)  # THE envelope; NaN counts as a violation
        if found:
            self.counts["violation_steps"] += 1
        for name, key in (
            ("outlet_above_max", "outlet_above_max_steps"),
            ("inlet_above_max", "inlet_above_max_steps"),
            ("inlet_below_min", "inlet_below_min_steps"),
            ("pue_above_max", "pue_above_max_steps"),
        ):
            self.counts[key] += int(name in found)

    def metrics(self) -> dict[str, float]:
        return {
            "mean_pue": float(np.mean(self.pue)),
            "energy_kwh": float(self.energy_kwh),
            "water_L": float(self.water_L),
            "mean_outlet_C": float(np.mean(self.outlet)),
            "max_outlet_C": float(np.max(self.outlet)),
            "mean_inlet_C": float(np.mean(self.inlet)),
            "max_inlet_C": float(np.max(self.inlet)),
            **{k: float(v) for k, v in self.counts.items()},
        }


def mean_over(episodes: Sequence[dict[str, float]]) -> dict[str, float]:
    """Mean of each metric over episodes (violation counts therefore read 'steps per episode')."""
    return {m: float(np.mean([e[m] for e in episodes])) for m in METRICS}


# ----------------------------------------------------------------------------- Study 1: physics 1 through the harness


def _load_harness() -> Any:
    from src import policy_evaluation as pe  # needs gymnasium via src.rl.env

    return pe


def study1_policies() -> list[Any]:
    from src.baselines.policies import ConstantPolicy, RulePolicy, actuator_range_C

    lo, hi = actuator_range_C("1")
    mid = (lo + hi) / 2.0
    return [
        RulePolicy(physics_version="1"),
        ConstantPolicy(lo, CONSTANT_MODE, physics_version="1"),
        ConstantPolicy(mid, CONSTANT_MODE, physics_version="1"),
        ConstantPolicy(hi, CONSTANT_MODE, physics_version="1"),
    ]


def scenarios_for(pe: Any, cfg: Any, per_family: int) -> list[Any]:
    """The first ``per_family`` VALIDATION scenarios of each family, in protocol order (never the test split)."""
    seen: dict[str, int] = {}
    out = []
    for s in pe.build_scenarios(cfg)["validation"]:
        if seen.get(s.family, 0) < per_family:
            seen[s.family] = seen.get(s.family, 0) + 1
            out.append(s)
    return out


Trace = list[tuple[float, float, float]]  # per step: (utilisation, outside temperature C, water stress)


def run_episode_metrics(
    pe: Any, policy: Any, scenario: Any, cfg: Any, curve: np.ndarray
) -> tuple[dict[str, float], Trace]:
    acc = _Acc()
    trace: Trace = []
    dt_h = pe.INTERVAL_MIN / 60.0

    def on_step(_before: dict[str, Any], _reward: float, after: dict[str, Any]) -> None:
        acc.add(
            float(after["inlet_temp"]),
            float(after["outlet_temp"]),
            float(after["pue"]),
            float(after["it_power"]) + float(after["cooling_power"]),
            float(after["water_consumed"]),
            dt_h,
        )
        trace.append((float(after["utilisation"]), float(after["outside_temp"]), float(scenario.water_stress)))

    pe.run_episode(policy, scenario, cfg, curve, on_step=on_step)
    return acc.metrics(), trace


def run_set(
    pe: Any, policies: Sequence[Any], scenarios: Sequence[Any], cfg: Any, curve: np.ndarray
) -> dict[str, dict[str, float]]:
    return {p.name: mean_over([run_episode_metrics(pe, p, s, cfg, curve)[0] for s in scenarios]) for p in policies}


def study1(per_family: int, progress: Callable[[str], None]) -> tuple[dict[str, Any], dict[str, Trace]]:
    pe = _load_harness()
    cfg = pe.EvalConfig(physics_version="1")
    curve, _is_real = pe.load_diurnal_carbon_intensity()  # no reported metric uses carbon; the env needs a curve
    scenarios = scenarios_for(pe, cfg, per_family)
    policies = study1_policies()
    baseline = run_set(pe, policies, scenarios, cfg, curve)
    # The exogenous trace is policy-independent (the harness asserts identical exogenous hashes); keep the rule's.
    traces = {s.scenario_id: run_episode_metrics(pe, policies[0], s, cfg, curve)[1] for s in scenarios}
    params: dict[str, Any] = {}
    for param in registry_v1():
        base = param.base()
        entry: dict[str, Any] = {
            "group": param.group,
            "where": param.where,
            "default": param.documented_value(),
            "levels": {},
        }
        if base == 0.0:
            entry["skipped"] = "default is 0, so a relative perturbation changes nothing"
            params[param.name] = entry
            continue
        for factor, label in zip(FACTORS, LEVEL_LABELS):
            with perturbed(param, factor) as value:
                results = run_set(pe, policies, scenarios, cfg, curve)
                entry["levels"][label] = {"value": param.doc_scale * value, "policies": results}
        params[param.name] = entry
        progress(f"physics 1: {param.name}")
    doc = {
        "scenarios": [s.scenario_id for s in scenarios],
        "policies": [p.name for p in policies],
        "baseline": baseline,
        "parameters": params,
        "not_perturbable": dict(V1_LITERALS),
        "v2_only": list(V2_ONLY),
    }
    return doc, traces


# ----------------------------------------------------------------------------- Study 2: physics 2, twin only, open loop


Control = Callable[[float, float], tuple[float, str]]  # (outside temperature C, water stress) -> (set-point C, mode)


def study2_controls() -> list[tuple[str, Control]]:
    from src.baselines.policies import actuator_range_C, default_rule_setpoint_C

    lo, hi = actuator_range_C("1")  # the same three set-points as Study 1 (they are inside physics 2's input range)
    selector = DigitalTwin(physics_version="1")
    rule_c = default_rule_setpoint_C("1")

    def rule(outside: float, stress: float) -> tuple[float, str]:
        return rule_c, selector.select_cooling_mode(outside, stress).value

    def const(c: float) -> Control:
        return lambda outside, stress: (c, CONSTANT_MODE)

    mid = (lo + hi) / 2
    return [
        ("rule_baseline", rule),
        (f"constant[{lo:g}C,{CONSTANT_MODE}]", const(lo)),
        (f"constant[{mid:g}C,{CONSTANT_MODE}]", const(mid)),
        (f"constant[{hi:g}C,{CONSTANT_MODE}]", const(hi)),
    ]


def run_twin_v2(params: PhysicsParams, control: Control, trace: Trace) -> tuple[dict[str, float], float]:
    """One open-loop episode on the physics-2 twin. Returns (metrics, largest |closure residual| in kJ)."""
    twin = DigitalTwin(
        physics_version="2",
        physics_params=params,
        initial_cooling_mode=CoolingMode.CLOSED_LOOP,
        initial_chilled_water_temp_C=10.0,
        start_time=datetime(2000, 1, 1),
    )
    acc = _Acc()
    worst = 0.0
    for util, outside, stress in trace:
        chilled, mode = control(outside, stress)
        action = {
            "utilisation": util,
            "outside_temp_C": outside,
            "water_stress": stress,
            "cooling_mode": mode,
            "chilled_water_temp_C": chilled,
        }
        s = twin.step(action)
        water_l = s.water_flow_lpm * 5.0  # litres per 5-minute step
        acc.add(s.server_inlet_temp_C, s.server_outlet_temp_C, s.pue, s.total_power_kw, water_l, 5.0 / 60.0)
        worst = max(worst, abs(float(twin.last_balance.get("closure_residual_kj", 0.0))))
    return acc.metrics(), worst


def run_set_v2(
    params: PhysicsParams, controls: Sequence[Any], traces: dict[str, Trace]
) -> tuple[dict[str, dict[str, float]], float]:
    out: dict[str, dict[str, float]] = {}
    worst = 0.0
    for name, control in controls:
        eps = []
        for trace in traces.values():
            m, w = run_twin_v2(params, control, trace)
            eps.append(m)
            worst = max(worst, w)
        out[name] = mean_over(eps)
    return out, worst


def v2_fields(base: PhysicsParams) -> list[str]:
    return [f.name for f in dataclasses.fields(base) if getattr(base, f.name) is not None]


def study2(traces: dict[str, Trace], progress: Callable[[str], None]) -> dict[str, Any]:
    base = PhysicsParams()
    controls = study2_controls()
    baseline, base_resid = run_set_v2(base, controls, traces)
    params: dict[str, Any] = {}
    worst_resid = base_resid
    for name in v2_fields(base):
        default = float(getattr(base, name))
        entry: dict[str, Any] = {"default": default, "levels": {}}
        if default == 0.0:
            entry["skipped"] = "default is 0, so a relative perturbation changes nothing"
            params[name] = entry
            continue
        for factor, label in zip(FACTORS, LEVEL_LABELS):
            value = default * factor
            try:
                changed = dataclasses.replace(base, **{name: value})
                policies, resid = run_set_v2(changed, controls, traces)
                worst_resid = max(worst_resid, resid)
                entry["levels"][label] = {"value": value, "policies": policies}
            except (PhysicsParamsError, PhysicsStabilityError, InvalidInputError) as exc:
                # The model's own validation refused this value: reported, never hidden or clipped.
                entry["levels"][label] = {"value": value, "rejected": f"{type(exc).__name__}: {exc}"}
        params[name] = entry
        progress(f"physics 2: {name}")
    return {
        "twin_only": True,
        "open_loop_replay": True,
        "policies": [n for n, _ in controls],
        "baseline": baseline,
        "parameters": params,
        "max_abs_closure_residual_kj": worst_resid,
    }


# ----------------------------------------------------------------------------- output


def _round(obj: Any) -> Any:
    if isinstance(obj, float):
        return round(obj, REPORT_ROUND) if math.isfinite(obj) else str(obj)
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round(v) for v in obj]
    return obj


def environment() -> dict[str, Any]:
    gym_version = "not installed"
    try:
        import gymnasium

        gym_version = getattr(gymnasium, "__version__", "unknown")
    except ImportError:
        pass
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "gymnasium": gym_version,
    }


def delta(base: float, new: float, kind: str) -> float:
    """Relative change in % for continuous metrics, absolute change for temperatures and step counts."""
    if kind == "pct":
        return float("nan") if base == 0 else (new - base) / abs(base) * 100.0
    return new - base


COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("mean_pue", "pct", "mean PUE %"),
    ("energy_kwh", "pct", "energy %"),
    ("max_outlet_C", "abs", "max outlet C"),
    ("max_inlet_C", "abs", "max inlet C"),
    ("violation_steps", "abs", "violation steps"),
)


def _fmt(v: float, kind: str) -> str:
    if v != v:
        return "n/a"
    if kind == "pct":
        return f"{v:+.2f}"
    return f"{v:+.2f}"


def markdown_table(study: dict[str, Any], policy: str, order_by: str = "mean_pue") -> str:
    """One table: per parameter, the change of each metric for ``policy`` at -25 % and +25 % of the default."""
    base = study["baseline"][policy]
    head = ["parameter", "default"] + [f"{label} (-25% / +25%)" for _, _, label in COLUMNS]
    rows: list[tuple[float, list[str]]] = []
    for name, p in study["parameters"].items():
        lv = p.get("levels", {})
        lo, hi = lv.get("-25%", {}), lv.get("+25%", {})
        if "skipped" in p or not lo or not hi:
            continue
        if "rejected" in lo or "rejected" in hi:
            mark = ("rejected" if "rejected" in lo else "") + " / " + ("rejected" if "rejected" in hi else "")
            rows.append((-1.0, [name, f"{p['default']:g}", mark] + [""] * (len(COLUMNS) - 1)))
            continue
        cells = [name, f"{p['default']:g}"]
        key = 0.0
        for metric, kind, _ in COLUMNS:
            a = delta(base[metric], lo["policies"][policy][metric], kind)
            b = delta(base[metric], hi["policies"][policy][metric], kind)
            cells.append(f"{_fmt(a, kind)} / {_fmt(b, kind)}")
            if metric == order_by:
                key = max(abs(a) if a == a else 0.0, abs(b) if b == b else 0.0)
        rows.append((key, cells))
    rows.sort(key=lambda r: (-r[0], r[1][0]))
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    lines += ["| " + " | ".join(c) + " |" for _, c in rows]
    return "\n".join(lines)


def inert_parameters(study: dict[str, Any]) -> list[str]:
    """Parameters whose perturbation changed NO metric of NO policy at ANY level (not binding in this setup)."""
    out = []
    for name, p in study["parameters"].items():
        if "skipped" in p or not p["levels"]:
            continue
        changed = False
        for lvl in p["levels"].values():
            if "rejected" in lvl:
                changed = True
                continue
            for pol, m in lvl["policies"].items():
                if any(m[k] != study["baseline"][pol][k] for k in METRICS):
                    changed = True
        if not changed:
            out.append(name)
    return out


def new_violations(study: dict[str, Any]) -> list[tuple[str, str, str, float]]:
    """(parameter, level, policy, violation steps per episode) where a perturbation CREATES violations the unperturbed
    baseline does not have."""
    out = []
    for name, p in study["parameters"].items():
        for label, lvl in p.get("levels", {}).items():
            if "rejected" in lvl:
                continue
            for pol, m in lvl["policies"].items():
                if m["violation_steps"] > study["baseline"][pol]["violation_steps"]:
                    out.append((name, label, pol, m["violation_steps"]))
    return out


def render_markdown(result: dict[str, Any]) -> str:
    env = result["environment"]
    out = [
        f"Environment: Python {env['python']}, numpy {env['numpy']}, gymnasium {env['gymnasium']}, {env['platform']}.",
        f"results_sha256: `{result['results_sha256']}`",
        "",
    ]
    titles = (
        ("physics1", "Study 1 - physics 1, repo harness"),
        ("physics2", "Study 2 - physics 2, twin only, open-loop replay"),
    )
    for key, title in titles:
        study = result.get(key)
        if not study:
            continue
        out += [f"### {title}", ""]
        if key == "physics1":
            out += [f"Scenarios (validation split): {', '.join(study['scenarios'])}", ""]
        out.append("Baseline (unperturbed):")
        out.append("")
        out.append("| policy | " + " | ".join(METRICS) + " |")
        out.append("|" + "|".join("---" for _ in range(len(METRICS) + 1)) + "|")
        for pol, m in study["baseline"].items():
            out.append(f"| {pol} | " + " | ".join(f"{m[k]:.4g}" for k in METRICS) + " |")
        out.append("")
        for pol in study["policies"]:
            heading = (
                f"**{pol}** - change vs. unperturbed, at -25% / +25% of the default (sorted by |change of mean PUE|):"
            )
            out += [heading, "", markdown_table(study, pol), ""]
        inert = inert_parameters(study)
        listed = ", ".join(inert) if inert else "none"
        out.append(f"Parameters that changed NO metric of NO policy at any level (not binding here): {listed}.")
        out.append("")
        nv = new_violations(study)
        out.append(f"Perturbations that CREATE envelope violations the unperturbed baseline does not have: {len(nv)}.")
        for name, label, pol, steps in nv[:40]:
            out.append(f"- {name} {label}, {pol}: {steps:.1f} violation steps per episode")
        out.append("")
        if key == "physics1":
            literals = "; ".join(f"{k} ({v})" for k, v in study["not_perturbable"].items())
            out.append(f"Documented but not perturbable in physics 1 (literal in the equations): {literals}.")
            out.append("")
        if key == "physics2":
            residual = study["max_abs_closure_residual_kj"]
            out.append(f"Largest per-step energy-closure residual seen over every run: {residual:.3e} kJ.")
            out.append("")
    return "\n".join(out)


def build(per_family: int, studies: Sequence[str], progress: Callable[[str], None]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "factors": list(FACTORS),
        "environment": environment(),
        "constant_mode": CONSTANT_MODE,
    }
    traces: dict[str, Trace] = {}
    if "physics1" in studies or "physics2" in studies:
        s1, traces = study1(per_family, progress) if "physics1" in studies else ({}, {})
        if "physics1" in studies:
            result["physics1"] = s1
    if "physics2" in studies:
        if not traces:  # study 2 alone still needs the exogenous traces: take them from a baseline-only harness pass
            pe = _load_harness()
            cfg = pe.EvalConfig(physics_version="1")
            curve, _is_real = pe.load_diurnal_carbon_intensity()
            rule = study1_policies()[0]
            chosen = scenarios_for(pe, cfg, per_family)
            traces = {s.scenario_id: run_episode_metrics(pe, rule, s, cfg, curve)[1] for s in chosen}
        result["physics2"] = study2(traces, progress)
    result = _round(result)
    digest_src = {k: result[k] for k in ("physics1", "physics2") if k in result}
    canonical = json.dumps(digest_src, sort_keys=True, separators=(",", ":")).encode()
    result["results_sha256"] = hashlib.sha256(canonical).hexdigest()
    return result


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--scenarios-per-family", type=int, default=3, help="validation scenarios per family (default 3, 9 in all)"
    )
    ap.add_argument("--studies", nargs="+", choices=("physics1", "physics2"), default=["physics1", "physics2"])
    ap.add_argument("--format", choices=("markdown", "json"), default="markdown")
    ap.add_argument("--out", type=Path, help="write the output here instead of stdout")
    ns = ap.parse_args(argv)
    if ns.scenarios_per_family < 1:
        ap.error("--scenarios-per-family must be >= 1")
    result = build(ns.scenarios_per_family, ns.studies, lambda msg: print(msg, file=sys.stderr, flush=True))
    text = render_markdown(result) if ns.format == "markdown" else json.dumps(result, indent=1, sort_keys=True)
    if ns.out:
        ns.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
