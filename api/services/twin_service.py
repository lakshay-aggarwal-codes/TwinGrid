"""Digital twin singleton + business logic for /api/state and /api/simulate."""

from __future__ import annotations

from typing import Any

from src.digital_twin import CoolingMode, DigitalTwin

_twin: DigitalTwin | None = None


def get_twin() -> DigitalTwin:
    """Get or create the shared DigitalTwin instance.

    NOTE: single shared instance across all requests, matching pre-refactor
    behaviour exactly. Multi-tenant / per-session twin instances are a
    later-phase (scale) concern, not addressed by this structural refactor.
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
    return state.to_dict()


def compute_simulation(hours: int, utilisation: float, stress: float) -> list[dict[str, Any]]:
    """Returns raw hourly records (timestamps NOT yet serialized)."""
    if hours < 1 or hours > 168:
        raise ValueError("hours must be between 1 and 168")
    twin = get_twin()
    steps_per_hour = 12
    n_steps = hours * steps_per_hour
    df = twin.run_scenario(
        n_steps=n_steps,
        util_profile=[utilisation] * n_steps,
        temp_profile=[25.0] * n_steps,
        use_auto_cooling=True,
        water_stress=stress,
    )
    return df.iloc[::steps_per_hour].to_dict("records")