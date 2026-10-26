"""Scenario registry (BC-09): backend-owned identities for the what-if presets.

A scenario here is a NAMED PRESET over the parameters of ``GET /api/whatif``. It
adds no physics: running a scenario calls the same isolated 24 h digital-twin
computation as a raw what-if, with the scenario's values filled in for any
parameter the caller did not supply. The registry only gives presets a stable,
opaque ``id`` and describes, per descriptor, where the weather input and the plant
come from, so a client never has to infer either from a name.

Descriptor vocabulary (authoritative; clients must treat unknown values as unknown):

* ``kind``            one of ``SCENARIO_KINDS``
* ``weather_source``  ``constant_input``: ONE caller/preset-supplied outside temperature held
                      for the whole 24 h run. It is NOT a reference or recorded weather series.
* ``plant``           ``simulated``: the in-repo DigitalTwin; never a real facility.
* ``control``         always ``none``: a scenario is evaluated, nothing is sent to a facility.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Final

from src.rl.env import CHILLED_WATER_ACTION_RANGE_C

REGISTRY_VERSION: Final[str] = "1"
WHATIF_ENDPOINT: Final[str] = "/api/whatif"

SCENARIO_KINDS: Final[tuple[str, ...]] = ("weather", "heat-wave", "drought", "workload", "physics-perturbation")
COOLING_MODES: Final[tuple[str, ...]] = ("auto", "free_air", "closed_loop", "evaporative", "hybrid")

# Single source of truth for /api/whatif bounds: the route imports these, and the parameter schema
# below is generated from them, so the schema cannot drift from what the endpoint enforces.
UTILISATION_BOUNDS: Final = (0.0, 1.0)
OUTSIDE_TEMP_BOUNDS: Final = (-10.0, 50.0)
WATER_STRESS_BOUNDS: Final = (0.0, 1.0)
CHILLED_WATER_TEMP_BOUNDS: Final = (5.0, 15.0)

# The widest chilled-water set-point any supported physics can command (legacy-0 5..15 C, physics 1 16..25 C, read from
# the environment's own table). It is only the OUTER limit written into the query schema; the limit a request is held
# to is ``accepted_chilled_water_range()``, which follows the physics the server is running (Task 3 rule).
CHILLED_WATER_TEMP_QUERY_BOUNDS: Final = (
    min(CHILLED_WATER_TEMP_BOUNDS[0], *(lo for lo, _ in CHILLED_WATER_ACTION_RANGE_C.values())),
    max(CHILLED_WATER_TEMP_BOUNDS[1], *(hi for _, hi in CHILLED_WATER_ACTION_RANGE_C.values())),
)

CHILLED_WATER_TEMP_DESCRIPTION: Final = (
    "Chilled-water setpoint (°C). Held to the running physics' range: 5-15 under legacy-0, 5-25 under physics 1."
)


def accepted_chilled_water_range(physics_version: str | None = None) -> tuple[float, float]:
    """The chilled-water set-points ``/api/whatif`` and ``/api/whatif/sensitivity`` accept for the running physics.

    The union of the registry bounds and the physics' actuator range (the same rule as the optimizer proposals:
    ``src.optimizer_proposals.accepted_chilled_range_C``): legacy-0 stays exactly 5..15 C, physics 1 is 5..25 C, so the
    What-if Lab can send any value of the range it reads from the server. Read per request, because the physics is not
    fixed at import. A physics the RL environment cannot run (``2``) has no actuator range: the registry bounds apply.
    """
    from src.optimizer_proposals import accepted_chilled_range_C
    from src.rl.env import UnsupportedPhysicsVersionForRL

    try:
        return accepted_chilled_range_C(CHILLED_WATER_TEMP_BOUNDS, physics_version)
    except UnsupportedPhysicsVersionForRL:
        return CHILLED_WATER_TEMP_BOUNDS


def chilled_water_range_error(value: float, physics_version: str | None = None) -> str | None:
    """None when ``value`` is accepted for the running physics, else the message a 422 carries."""
    lo, hi = accepted_chilled_water_range(physics_version)
    if lo <= value <= hi:
        return None
    return f"chilled_water_temp must be between {lo:g} and {hi:g} C for the running physics, got {value:g}"


# Defaults used by /api/whatif when neither the caller nor a scenario supplies a value.
WHATIF_DEFAULTS: Final = MappingProxyType(
    {
        "utilisation": 0.65,
        "outside_temp": 22.0,
        "water_stress": 0.0,
        "mode": "auto",
        "chilled_water_temp": 7.0,
    }
)


def _parameter_schema(defaults: dict[str, Any]) -> list[dict[str, Any]]:
    def num(name: str, unit: str | None, bounds: tuple[float, float], description: str) -> dict[str, Any]:
        return {
            "name": name,
            "type": "number",
            "unit": unit,
            "min": bounds[0],
            "max": bounds[1],
            "default": defaults[name],
            "description": description,
        }

    return [
        num("utilisation", None, UTILISATION_BOUNDS, "Server utilisation, fraction of capacity."),
        num("outside_temp", "°C", OUTSIDE_TEMP_BOUNDS, "Outside temperature held constant for the run."),
        num("water_stress", None, WATER_STRESS_BOUNDS, "Water-stress index, 0 (none) to 1 (severe)."),
        {
            "name": "mode",
            "type": "enum",
            "unit": None,
            "options": list(COOLING_MODES),
            "default": defaults["mode"],
            "description": "Cooling mode; 'auto' lets the twin's rule-based selector choose.",
        },
        num("chilled_water_temp", "°C", CHILLED_WATER_TEMP_QUERY_BOUNDS, CHILLED_WATER_TEMP_DESCRIPTION),
    ]


def _scenario(id_: str, label: str, kind: str, description: str, overrides: dict[str, Any]) -> dict[str, Any]:
    assert kind in SCENARIO_KINDS
    defaults = {**WHATIF_DEFAULTS, **overrides}
    return {
        "id": id_,
        "label": label,
        "kind": kind,
        "description": description,
        "weather_source": "constant_input",
        "plant": "simulated",
        "control": "none",
        "endpoint": WHATIF_ENDPOINT,
        "parameters": _parameter_schema(defaults),
    }


# Order is the display order. Ids are opaque and stable; never reuse one for different values.
_SCENARIOS: Final[tuple[dict[str, Any], ...]] = (
    _scenario(
        "whatif-baseline",
        "Baseline",
        "workload",
        "Moderate load, mild outside temperature, no water stress.",
        {},
    ),
    _scenario(
        "whatif-peak-workload",
        "Peak workload",
        "workload",
        "Server utilisation raised to 0.95 with all other inputs at baseline.",
        {"utilisation": 0.95},
    ),
    _scenario(
        "whatif-heat-wave",
        "Heat wave",
        "heat-wave",
        "Outside temperature held at 38 °C for the whole run.",
        {"outside_temp": 38.0},
    ),
    _scenario(
        "whatif-drought",
        "Drought",
        "drought",
        "Water stress held at 0.85, above the twin's drought-override threshold (0.7).",
        {"water_stress": 0.85},
    ),
)

_BY_ID: Final = {s["id"]: s for s in _SCENARIOS}


def list_scenarios() -> dict[str, Any]:
    """The registry payload for ``GET /api/scenarios`` (deep-copied: callers cannot mutate the registry)."""
    import copy

    return {"registry_version": REGISTRY_VERSION, "scenarios": copy.deepcopy(list(_SCENARIOS))}


def get_scenario(scenario_id: str) -> dict[str, Any] | None:
    return _BY_ID.get(scenario_id)


def whatif_provenance(scenario_id: str | None, api_version: str) -> dict[str, Any]:
    """What a ``/api/whatif`` answer is made of, using the vocabulary of a run result's ``provenance``.

    ``scenario_kind`` is null for a raw what-if. ``weather_source`` ``constant_input`` means ONE outside temperature held
    for the whole 24 h run, not a recorded series; ``model_version`` is null because a what-if applies no learned model.
    ``registry_version`` identifies the preset registry (the config) and ``api_version`` the code that served the answer.
    The physics version is reported once, at the top level of the response.
    """
    descriptor = _BY_ID.get(scenario_id) if scenario_id is not None else None
    return {
        "origin": "simulated",
        "scenario_kind": descriptor["kind"] if descriptor is not None else None,
        "weather_source": descriptor["weather_source"] if descriptor is not None else "constant_input",
        "plant": descriptor["plant"] if descriptor is not None else "simulated",
        "control": descriptor["control"] if descriptor is not None else "none",
        "model_version": None,
        "registry_version": REGISTRY_VERSION,
        "api_version": api_version,
    }


def scenario_defaults(scenario_id: str) -> dict[str, Any]:
    """Parameter name -> the scenario's preset value. Raises KeyError for an unknown id."""
    return {p["name"]: p["default"] for p in _BY_ID[scenario_id]["parameters"]}
