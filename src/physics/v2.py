"""Physics v2 -- a dynamic, lumped-capacitance data-centre model with explicit thermal and actuator state.

LEVEL (roadmap 13.1): "dynamic twin" -- explicit thermal-energy and actuator state, published parameters,
UNCALIBRATED. This is not a calibrated twin, not validated against any facility, and not high-fidelity; there is
no per-rack or per-aisle behaviour. All parameter values are PROPOSED (src/physics/params.py).

NOT MODELLED (roadmap 13.2):
  * per-rack / per-aisle airflow and recirculation (one well-mixed room, one server air stream)
  * compressor dynamics (COP is a static function of operating point; mode changes are instantaneous)
  * storage tanks (no thermal storage, no chilled-water loop volume)
  * electrical distribution losses (UPS, PDU, transformers; total = IT + cooling plant only)
  * basin / blowdown (water = evaporated heat only; no make-up, drift or concentration cycles)
  * equipment ageing (fouling, fan/chiller degradation)
  * weather forecasting (ambient and humidity are inputs for the current step only)

STATE (DynamicState):
  T_room          bulk room/equipment temperature [degC]; the only energy-storing state
  T_in, T_out     server inlet / outlet air temperature [degC] (first-order lag, no energy storage)
  T_chw_applied   chilled-water setpoint actually in force [degC] (rate limit + first-order lag)
  mode_applied    cooling mode physics actually used
  water_cum       cumulative evaporated water [L]

EQUATIONS (docs/PHYSICS_V2.md has units and derivations)
  C_th dT_room/dt = Q_it - Q_cool
  Q_cool          = min(capacity(ambient, humidity, mode), UA (T_room - T_sink)),  clamped to >= 0
  T_sink          = T_chw_applied (chiller modes) | ambient (free air)
Integration is semi-implicit Euler: implicit in the UA term, so the update is unconditionally stable for the
linear coil branch; the capacity-limited branch is a constant sink (explicit and exact). The step is checked
by ``check_step_stability``. By construction C_th (T_room' - T_room) = (Q_it - Q_cool) dt to floating-point
round-off, which is the per-step energy-closure invariant.

STEADY STATE vs v1: with constant inputs and Q_it below capacity, v2 settles at the v1 steady state (same
T_in/T_out, same cooling power, PUE, water) when humidity equals ``humidity_reference_pct``. Above capacity v1
has a finite algebraic inlet offset while v2 integrates an ever-warming room: this is a deliberate, documented
difference (an overloaded plant has no steady state).
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, replace
from typing import Optional

from .params import MODES, PhysicsParams

# Physical constants (identical to src/digital_twin.py; a test pins that).
SPECIFIC_HEAT_AIR_J_KG_K: float = 1005.0
AIR_DENSITY_KG_M3: float = 1.2
JOULES_PER_KWH: float = 3.6e6
WATER_DENSITY_KG_PER_L: float = 1.0

DEFAULT_SIM_STEP_SECONDS: float = 300.0
MAX_STEP_SECONDS: float = 3600.0
RATE_LIMIT_REFERENCE_SECONDS: float = 300.0  # chw_rate_limit_c_per_5min is defined per this interval


class PhysicsStabilityError(ValueError):
    """The requested time step is outside the range the v2 integrator is checked for."""


class PhysicsInputError(ValueError):
    """A v2 input is non-finite, mistyped or out of range."""


# ------------------------------------------------------------------------------------------------ data types
@dataclass(frozen=True)
class DynamicState:
    t_room_c: float
    t_in_c: float
    t_out_c: float
    t_chw_applied_c: float
    mode_applied: str
    water_cum_l: float = 0.0


@dataclass(frozen=True)
class StepInputs:
    utilisation: float
    outside_temp_c: float
    humidity_pct: float
    cooling_mode: str  # requested
    chw_requested_c: float

    def __post_init__(self) -> None:
        for name in ("utilisation", "outside_temp_c", "humidity_pct", "chw_requested_c"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise PhysicsInputError(f"{name} must be a finite number, got {value!r}")
        if not 0.0 <= self.utilisation <= 1.0:
            raise PhysicsInputError(f"utilisation must be in [0, 1], got {self.utilisation}")
        if not 0.0 <= self.humidity_pct <= 100.0:
            raise PhysicsInputError(f"humidity_pct must be in [0, 100], got {self.humidity_pct}")
        if self.cooling_mode not in MODES:
            raise PhysicsInputError(f"unknown cooling mode {self.cooling_mode!r}; known: {MODES}")


@dataclass(frozen=True)
class StepResult:
    state: DynamicState
    dt_s: float
    it_power_kw: float
    capacity_kw: float
    q_cool_kw: float  # heat actually removed from the room this step
    q_stored_kw: float  # Q_it - Q_cool: rate at which the room stores heat (can be negative)
    cooling_electrical_kw: float
    cop: float
    heat_rejected_kw: float  # Q_cool + cooling electrical (leaves through the plant)
    water_flow_lpm: float
    water_step_l: float
    room_energy_change_kj: float
    closure_residual_kj: float  # C_th dT_room - (Q_it - Q_cool) dt; ~0 by construction


@dataclass(frozen=True)
class StabilityReport:
    dt_s: float
    tau_room_s: float
    dt_over_tau: float
    room_amplification: float  # |1 / (1 + dt UA / C_th)| : the homogeneous error factor per step
    max_dt_s: float


# --------------------------------------------------------------------------------------------- step size
def sim_step_seconds() -> float:
    """The configured step ``SIM_STEP_SECONDS`` (env, default 300 s). Read on every call. Invalid -> error."""
    raw = os.getenv("SIM_STEP_SECONDS")
    if raw is None or not raw.strip():
        return DEFAULT_SIM_STEP_SECONDS
    try:
        value = float(raw)
    except ValueError:
        raise PhysicsStabilityError(f"SIM_STEP_SECONDS must be a number, got {raw!r}") from None
    if not math.isfinite(value) or value <= 0:
        raise PhysicsStabilityError(f"SIM_STEP_SECONDS must be finite and > 0, got {raw!r}")
    return value


def check_step_stability(params: PhysicsParams, dt_s: float) -> StabilityReport:
    """Verify ``dt_s`` for the v2 integrator; raise ``PhysicsStabilityError`` if it is not allowed.

    * The room update is implicit in the UA term, so its error factor 1/(1+dt/tau_room) lies in (0, 1] for
      every dt > 0: no oscillation, no blow-up.
    * T_in, T_out and T_chw use the exact exponential for a constant target (also unconditionally stable).
    * The capacity branch applies a constant Q_cool (explicit and exact for that step).
    The remaining risk is ACCURACY (first order in dt) and the number of regime switches inside one step, so
    dt is bounded by ``max_dt_over_tau`` x tau_room (default 4 -> 3600 s with the default parameters) and by the
    absolute ``MAX_STEP_SECONDS``, the same ceiling physics v1 uses.
    """
    if isinstance(dt_s, bool) or not isinstance(dt_s, (int, float)) or not math.isfinite(dt_s) or dt_s <= 0:
        raise PhysicsStabilityError(f"dt must be a finite number > 0, got {dt_s!r}")
    tau = params.room_time_constant_s
    max_dt = min(MAX_STEP_SECONDS, params.max_dt_over_tau * tau)
    if dt_s > max_dt:
        raise PhysicsStabilityError(
            f"dt={dt_s:g}s exceeds the checked maximum {max_dt:g}s "
            f"(min({MAX_STEP_SECONDS:g}s, {params.max_dt_over_tau:g} x tau_room={tau:g}s))"
        )
    return StabilityReport(
        dt_s=float(dt_s),
        tau_room_s=tau,
        dt_over_tau=dt_s / tau,
        room_amplification=1.0 / (1.0 + dt_s / tau),
        max_dt_s=max_dt,
    )


# -------------------------------------------------------------------------------------- humidity / wet bulb
def wet_bulb_c(temp_c: float, rh_pct: float) -> float:
    """Wet-bulb temperature, Stull (2011) approximation (valid RH 5-99 %, T -20..50 degC; inputs are
    clamped into that window and the result never exceeds the dry bulb)."""
    t = min(50.0, max(-20.0, temp_c))
    rh = min(99.0, max(5.0, rh_pct))
    tw = (
        t * math.atan(0.151977 * math.sqrt(rh + 8.313659))
        + math.atan(t + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * rh**1.5 * math.atan(0.023101 * rh)
        - 4.686035
    )
    return min(tw, t)


def wet_bulb_depression_c(temp_c: float, rh_pct: float) -> float:
    """Dry bulb minus wet bulb (>= 0): the potential for evaporative cooling."""
    t = min(50.0, max(-20.0, temp_c))
    return max(0.0, t - wet_bulb_c(temp_c, rh_pct))


def wet_bulb_factor(temp_c: float, rh_pct: float, params: PhysicsParams) -> float:
    """Evaporative potential relative to the reference humidity: depression(T, RH) / depression(T, RH_ref),
    clipped to [wet_bulb_factor_min, wet_bulb_factor_max]. Equals exactly 1.0 at RH_ref (and when the
    reference depression is negligible). Drier air -> > 1, more humid air -> < 1."""
    ref = wet_bulb_depression_c(temp_c, params.humidity_reference_pct)
    if ref < 0.1:
        return 1.0
    factor = wet_bulb_depression_c(temp_c, rh_pct) / ref
    return min(params.wet_bulb_factor_max, max(params.wet_bulb_factor_min, factor))


# ------------------------------------------------------------------------------------------ plant functions
def resolve_mode(requested: str, outside_temp_c: float, params: PhysicsParams) -> str:
    """Free air is only effective in cold weather; otherwise the plant runs hybrid (same rule as v1)."""
    if requested == "free_air" and outside_temp_c >= params.free_air_ineffective_above_c:
        return "hybrid"
    return requested


def it_power_kw(utilisation: float, params: PhysicsParams) -> float:
    """Existing parametric IT power curve: idle + (1 - idle) x utilisation, times the maximum."""
    idle = params.idle_power_fraction * params.max_it_power_kw
    return idle + (1.0 - params.idle_power_fraction) * utilisation * params.max_it_power_kw


def air_flow_m3_s(it_power: float, params: PhysicsParams) -> float:
    """Fan speed ramps linearly with load from the idle airflow to the full-load airflow."""
    load = max(0.0, min(1.0, it_power / params.max_it_power_kw))
    return params.air_flow_base_m3_s + (params.air_flow_full_load_m3_s - params.air_flow_base_m3_s) * load


def capacity_kw(mode: str, outside_temp_c: float, humidity_pct: float, params: PhysicsParams) -> float:
    """Heat the plant can remove: design capacity, derated when the heat-rejection temperature is high.

    The rejection temperature is the dry bulb shifted toward the wet bulb by the mode's evaporative share:
        T_rej = T_ambient - f_evap(mode) x (depression(T, RH) - depression(T, RH_ref))
    so humidity enters through the wet-bulb approximation, and at RH_ref it reduces to the v1 rule exactly.
    """
    shift = params.evap_fraction(mode) * (
        wet_bulb_depression_c(outside_temp_c, humidity_pct)
        - wet_bulb_depression_c(outside_temp_c, params.humidity_reference_pct)
    )
    t_rej = outside_temp_c - shift
    derate = 1.0 - params.capacity_derate_per_c * max(0.0, t_rej - params.capacity_derate_start_c)
    return params.design_capacity_kw * max(params.capacity_min_fraction, derate)


def cop(
    mode: str,
    it_power: float,
    outside_temp_c: float,
    humidity_pct: float,
    chw_applied_c: float,
    params: PhysicsParams,
) -> float:
    """The v1 COP functional form, every coefficient taken from ``params``."""
    load = max(0.0, min(1.0, it_power / params.max_it_power_kw))
    load_penalty = 1.0 - params.cop_load_derate * load
    outside_penalty = 1.0 - params.cop_outside_derate_per_c * max(
        0.0, outside_temp_c - params.cop_outside_derate_start_c
    )
    humidity_penalty = 1.0
    if mode == "evaporative":
        humidity_penalty = 1.0 - params.cop_humidity_derate_per_pct * max(
            0.0, humidity_pct - params.cop_humidity_reference_pct
        )
    water_temp_bonus = 1.0
    if mode in ("closed_loop", "hybrid"):
        water_temp_bonus = max(
            params.cop_chw_bonus_floor,
            1.0 + params.cop_chw_lift_per_c * (chw_applied_c - params.cop_chw_reference_c),
        )
    value = params.base_cop(mode) * load_penalty * outside_penalty * humidity_penalty * water_temp_bonus
    return max(value, params.cop_min)


def sink_temperature_c(mode: str, outside_temp_c: float, chw_applied_c: float) -> float:
    """What the coil rejects heat to: the applied chilled water, or outside air in free-air mode."""
    return outside_temp_c if mode == "free_air" else chw_applied_c


def supply_air_c(mode: str, outside_temp_c: float, chw_applied_c: float, params: PhysicsParams) -> float:
    """Supply-air temperature (v1 rule): held at or above the floor; free air = ambient + fan heat."""
    if mode == "free_air":
        return max(params.inlet_supply_floor_c, outside_temp_c + params.free_air_fan_heat_c)
    return max(params.inlet_supply_floor_c, chw_applied_c + params.chw_approach_c)


def actuator_step(prev_c: float, requested_c: float, dt_s: float, params: PhysicsParams) -> float:
    """Chilled-water actuator: first-order lag toward the request, with a hard slew-rate limit.

    delta = (1 - exp(-dt/tau_chw)) x (requested - prev)
    |delta| <= chw_rate_limit_c_per_5min x dt / 300        (enforced exactly)
    """
    alpha = 1.0 - math.exp(-dt_s / (params.tau_chw_min * 60.0))
    limit = params.chw_rate_limit_c_per_5min * dt_s / RATE_LIMIT_REFERENCE_SECONDS
    delta = alpha * (requested_c - prev_c)
    return prev_c + max(-limit, min(limit, delta))


def water_step(
    mode: str,
    outside_temp_c: float,
    humidity_pct: float,
    q_removed_kw: float,
    cooling_electrical_kw: float,
    dt_s: float,
    params: PhysicsParams,
) -> tuple[float, float]:
    """(flow L/min, litres this step): evaporated heat, never above the latent-heat bound.

        share   = min(1, f_evap(mode) x warm_factor(T) x wet_bulb_factor(T, RH))
        water   = share x (Q_removed + P_cooling) x dt x (3.6e6 / latent_heat)   [L]
    Per-step rate plus a running counter -- no basin, blowdown or make-up water.
    """
    fraction = params.evap_fraction(mode)
    if fraction <= 0.0:
        return 0.0, 0.0
    warm = 1.0 + params.water_warm_factor_per_c * max(0.0, outside_temp_c - params.water_warm_reference_c)
    share = min(1.0, fraction * warm * wet_bulb_factor(outside_temp_c, humidity_pct, params))
    rejected_kw = max(0.0, q_removed_kw) + max(0.0, cooling_electrical_kw)
    litres_per_kwh = JOULES_PER_KWH / (params.latent_heat_j_per_kg * WATER_DENSITY_KG_PER_L)
    litres = share * rejected_kw * (dt_s / 3600.0) * litres_per_kwh
    return litres / (dt_s / 60.0), litres


# ------------------------------------------------------------------------------------- initial state, step
def initial_state(inputs: StepInputs, params: PhysicsParams, chw_initial_c: float) -> DynamicState:
    """Settled starting point (like v1, which starts at its steady state): T_room where the coil exactly
    carries the load (or at the capacity-saturation temperature if the load exceeds capacity)."""
    mode = resolve_mode(inputs.cooling_mode, inputs.outside_temp_c, params)
    p_it = it_power_kw(inputs.utilisation, params)
    sink = sink_temperature_c(mode, inputs.outside_temp_c, chw_initial_c)
    cap = capacity_kw(mode, inputs.outside_temp_c, inputs.humidity_pct, params)
    t_in = supply_air_c(mode, inputs.outside_temp_c, chw_initial_c, params)
    m_cp = AIR_DENSITY_KG_M3 * air_flow_m3_s(p_it, params) * SPECIFIC_HEAT_AIR_J_KG_K
    return DynamicState(
        t_room_c=sink + min(p_it, cap) / params.coil_ua_kw_per_k,
        t_in_c=t_in,
        t_out_c=t_in + p_it * 1000.0 / m_cp,
        t_chw_applied_c=chw_initial_c,
        mode_applied=mode,
        water_cum_l=0.0,
    )


def step(state: DynamicState, inputs: StepInputs, dt_s: float, params: PhysicsParams) -> StepResult:
    """Advance the dynamic state by ``dt_s`` seconds. Pure: the same (state, inputs, dt, params) always
    produce the same result and nothing is mutated."""
    check_step_stability(params, dt_s)

    mode = resolve_mode(inputs.cooling_mode, inputs.outside_temp_c, params)
    chw = actuator_step(state.t_chw_applied_c, inputs.chw_requested_c, dt_s, params)

    p_it = it_power_kw(inputs.utilisation, params)
    cap = capacity_kw(mode, inputs.outside_temp_c, inputs.humidity_pct, params)
    sink = sink_temperature_c(mode, inputs.outside_temp_c, chw)
    c_th = params.thermal_capacitance_kj_per_k
    ua = params.coil_ua_kw_per_k

    # Semi-implicit Euler: implicit in the UA term. t_imp solves  C (t - t0) = dt (Q_it - UA (t - sink)).
    t_imp = (state.t_room_c + dt_s / c_th * (p_it + ua * sink)) / (1.0 + dt_s * ua / c_th)
    q_imp = ua * (t_imp - sink)
    q_cool = min(max(q_imp, 0.0), cap)  # a coil cannot heat the room; the plant cannot exceed capacity
    if q_cool == q_imp:
        t_room = t_imp
    else:  # capacity-limited (or coil idle): Q_cool is a constant over the step
        t_room = state.t_room_c + dt_s * (p_it - q_cool) / c_th

    # Server air path. The room only reaches the inlet once the coil is saturated at capacity.
    t_saturation = sink + cap / ua
    excess_c = max(0.0, t_room - t_saturation)
    t_in_target = supply_air_c(mode, inputs.outside_temp_c, chw, params) + excess_c
    m_cp = AIR_DENSITY_KG_M3 * air_flow_m3_s(p_it, params) * SPECIFIC_HEAT_AIR_J_KG_K
    t_out_target = t_in_target + p_it * 1000.0 / m_cp
    alpha_air = 1.0 - math.exp(-dt_s / (params.tau_air_min * 60.0))
    t_in = state.t_in_c + alpha_air * (t_in_target - state.t_in_c)
    t_out = state.t_out_c + alpha_air * (t_out_target - state.t_out_c)

    cop_value = cop(mode, p_it, inputs.outside_temp_c, inputs.humidity_pct, chw, params)
    cooling = q_cool / cop_value
    flow_lpm, litres = water_step(mode, inputs.outside_temp_c, inputs.humidity_pct, q_cool, cooling, dt_s, params)

    new_state = DynamicState(
        t_room_c=t_room,
        t_in_c=t_in,
        t_out_c=t_out,
        t_chw_applied_c=chw,
        mode_applied=mode,
        water_cum_l=state.water_cum_l + litres,
    )
    delta_kj = c_th * (t_room - state.t_room_c)
    return StepResult(
        state=new_state,
        dt_s=float(dt_s),
        it_power_kw=p_it,
        capacity_kw=cap,
        q_cool_kw=q_cool,
        q_stored_kw=p_it - q_cool,
        cooling_electrical_kw=cooling,
        cop=cop_value,
        heat_rejected_kw=q_cool + cooling,
        water_flow_lpm=flow_lpm,
        water_step_l=litres,
        room_energy_change_kj=delta_kj,
        closure_residual_kj=delta_kj - (p_it - q_cool) * dt_s,
    )


def with_water_cum(state: DynamicState, water_cum_l: float) -> DynamicState:
    return replace(state, water_cum_l=water_cum_l)


__all__: Optional[list[str]] = [
    "AIR_DENSITY_KG_M3",
    "DEFAULT_SIM_STEP_SECONDS",
    "DynamicState",
    "MAX_STEP_SECONDS",
    "PhysicsInputError",
    "PhysicsStabilityError",
    "SPECIFIC_HEAT_AIR_J_KG_K",
    "StabilityReport",
    "StepInputs",
    "StepResult",
    "actuator_step",
    "air_flow_m3_s",
    "capacity_kw",
    "check_step_stability",
    "cop",
    "initial_state",
    "it_power_kw",
    "resolve_mode",
    "sim_step_seconds",
    "step",
    "supply_air_c",
    "water_step",
    "wet_bulb_c",
    "wet_bulb_factor",
    "with_water_cum",
]
