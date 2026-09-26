"""Digital twin singleton + business logic for /api/state, /api/simulate and /api/whatif."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Optional

from src.digital_twin import INTERVAL_MINUTES, CoolingMode, DigitalTwin

_twin: Optional[DigitalTwin] = None

STEPS_PER_HOUR = 60 // INTERVAL_MINUTES
WHATIF_HOURS = 24

# Diurnal-curve amplitudes for compute_simulation(). The requested
# utilisation/outside_temp are treated as the DAY'S MEAN, not a flat value
# held for the whole run -- these swing around that mean by time-of-day,
# using the same phase DataCentreEnv uses for its own training-time profile
# (src/optimizer.py: _compute_utilisation peaks ~midday, _compute_outside_temp
# peaks mid-afternoon), just anchored to the caller's mean instead of a fixed
# baseline.
_UTIL_DIURNAL_AMPLITUDE = 0.15
_OUTSIDE_TEMP_DIURNAL_AMPLITUDE_C = 4.0


def _diurnal_utilisation(mean_utilisation: float, n_steps: int, start_time: datetime) -> list[float]:
    values = []
    for i in range(n_steps):
        t = start_time + timedelta(minutes=i * INTERVAL_MINUTES)
        hour = t.hour + t.minute / 60.0
        v = mean_utilisation + _UTIL_DIURNAL_AMPLITUDE * math.sin((hour - 6) * math.pi / 12)
        values.append(float(min(1.0, max(0.0, v))))
    return values


def _diurnal_outside_temp(mean_outside_temp_C: float, n_steps: int, start_time: datetime) -> list[float]:
    values = []
    for i in range(n_steps):
        t = start_time + timedelta(minutes=i * INTERVAL_MINUTES)
        hour = t.hour + t.minute / 60.0
        v = mean_outside_temp_C + _OUTSIDE_TEMP_DIURNAL_AMPLITUDE_C * math.sin(2 * math.pi * (hour - 14) / 24)
        values.append(float(v))
    return values


def get_twin() -> DigitalTwin:
    """Get or create the shared DigitalTwin instance.

    NOTE: single shared instance across all requests, matching pre-refactor
    behaviour exactly. It backs the *live* views only (/api/state and the
    WebSocket broadcast). Anything that runs a scenario forward in time
    (/api/simulate, /api/whatif) must NOT use it -- see compute_simulation.
    Multi-tenant / per-session twin instances are a later-phase (scale)
    concern, not addressed by this structural refactor.
    """
    global _twin
    if _twin is None:
        _twin = DigitalTwin()
    return _twin


def compute_state(utilisation: float, outside_temp: float, water_stress: float, mode: str) -> dict[str, Any]:
    twin = get_twin()
    action: dict[str, Any] = {
        "utilisation": utilisation,
        "outside_temp_C": outside_temp,
        "water_stress": water_stress,
    }
    if mode == "auto":
        cooling_mode = twin.select_cooling_mode(outside_temp, water_stress)
    else:
        try:
            cooling_mode = CoolingMode(mode)
        except ValueError:
            cooling_mode = CoolingMode.CLOSED_LOOP
    action["cooling_mode"] = cooling_mode
    state = twin.step(action)
    return {**state.to_dict(), "carbon_data_is_real": twin.carbon_data_is_real}


def compute_simulation(hours: int, utilisation: float, outside_temp: float, stress: float) -> list[dict[str, Any]]:
    """Returns raw hourly records (timestamps NOT yet serialized -- callers
    must pass them through api.serialization.to_jsonable).

    Blocking and CPU-bound: call it via ``run_in_threadpool`` from async code.

    Uses a FRESH DigitalTwin, never the shared singleton: run_scenario()
    advances the twin's clock and thermal state and accumulates
    ``water_consumed_L`` for as long as the instance lives, so on the shared
    twin every call would start from wherever the previous one (or the live
    WebSocket feed) left off -- and would also perturb the live feed.

    ``utilisation`` and ``outside_temp`` are the requested MEANS for the run,
    not held flat for the whole period -- they're the center of a diurnal
    curve (see _diurnal_utilisation/_diurnal_outside_temp above), so the
    24h/168h chart actually has time-of-day shape to react to instead of a
    flat line and a single-color cooling-mode donut.
    """
    if hours < 1 or hours > 168:
        raise ValueError("hours must be between 1 and 168")
    twin = DigitalTwin()
    n_steps = hours * STEPS_PER_HOUR
    start_time = twin.state.timestamp
    util_profile = _diurnal_utilisation(utilisation, n_steps, start_time)
    temp_profile = _diurnal_outside_temp(outside_temp, n_steps, start_time)
    df = twin.run_scenario(
        n_steps=n_steps,
        util_profile=util_profile,
        temp_profile=temp_profile,
        use_auto_cooling=True,
        water_stress=stress,
    )
    return df.iloc[::STEPS_PER_HOUR].to_dict("records")


def compute_whatif(
    utilisation: float,
    outside_temp: float,
    water_stress: float,
    mode: str,
    chilled_water_temp: float,
) -> dict[str, Any]:
    """Steady-state 24 h scenario on an ISOLATED DigitalTwin.

    Every number returned is aggregated from the twin's own per-step output
    (nothing is estimated with a side formula): inputs are held constant for
    24 h of 5-minute steps, starting from a settled state at the requested
    chilled-water setpoint.

    Blocking and CPU-bound: call via ``run_in_threadpool``.
    """
    twin = DigitalTwin(initial_chilled_water_temp_C=chilled_water_temp)
    n_steps = WHATIF_HOURS * STEPS_PER_HOUR
    interval_h = INTERVAL_MINUTES / 60

    total_energy_kwh = 0.0
    it_energy_kwh = 0.0
    co2_g = 0.0
    pue_sum = 0.0
    max_outlet_c = float("-inf")
    last = None
    for _ in range(n_steps):
        cooling_mode = (
            twin.select_cooling_mode(outside_temp, water_stress) if mode == "auto" else CoolingMode(mode)
        )
        last = twin.step(
            {
                "utilisation": utilisation,
                "outside_temp_C": outside_temp,
                "water_stress": water_stress,
                "cooling_mode": cooling_mode,
                "chilled_water_temp_C": chilled_water_temp,
            }
        )
        total_energy_kwh += last.total_power_kw * interval_h
        it_energy_kwh += last.it_power_kw * interval_h
        co2_g += last.carbon_intensity_gco2_per_kwh * last.total_power_kw * interval_h
        pue_sum += last.pue
        max_outlet_c = max(max_outlet_c, last.server_outlet_temp_C)

    # water_consumed_L is cumulative on the twin, so the last step's value is
    # the 24 h total; WUE uses the twin's own definition (L per IT kWh).
    total_water_l = last.water_consumed_L
    return {
        "hours": WHATIF_HOURS,
        "basis": "24h at constant inputs, isolated digital-twin run (no RL optimizer applied)",
        "inputs": {
            "utilisation": utilisation,
            "outside_temp_C": outside_temp,
            "water_stress": water_stress,
            "mode": mode,
            "chilled_water_temp_C": chilled_water_temp,
        },
        "mean_pue": pue_sum / n_steps,
        "wue": total_water_l / it_energy_kwh if it_energy_kwh > 0 else 0.0,
        "total_water_L": total_water_l,
        "total_energy_kwh": total_energy_kwh,
        "total_co2_kg": co2_g / 1000.0,
        "max_outlet_temp_C": max_outlet_c,
        "final_cooling_mode": last.cooling_mode.value,
        "drought_override_active": bool(last.drought_override_active),
        "carbon_data_is_real": twin.carbon_data_is_real,
    }
