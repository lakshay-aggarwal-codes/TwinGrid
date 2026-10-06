"""Physics version registry.

Every number the digital twin produces comes from one named physics version, so
results from different versions are never silently mixed and an old version can
still be replayed.

* ``legacy-0``  the original equations, frozen. Selectable for replay and for
  the golden tests; its numerics are bit-identical to the pre-versioning code.
* ``1``         Physics v1: energy closure, a latent-heat water bound, finite
  cooling capacity, validated inputs, one carbon definition, one safety envelope
  and a reachable inlet band. See src/digital_twin.py.

Selection: ``DigitalTwin(physics_version=...)`` wins; otherwise the
``PHYSICS_VERSION`` environment variable; otherwise ``PHYSICS_VERSION`` below.
The environment is read on every call (not at import) so a deployment or a test
can switch without a reload. An unknown value raises: it never falls back.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import math
import os
import re
from typing import Any

LEGACY_PHYSICS_VERSION = "legacy-0"
PHYSICS_V1 = "1"
KNOWN_PHYSICS_VERSIONS: tuple[str, ...] = (LEGACY_PHYSICS_VERSION, PHYSICS_V1)

# The version new work is done under.
PHYSICS_VERSION = PHYSICS_V1


class PhysicsVersionError(ValueError):
    """Unknown physics version, or results from different versions being mixed."""


def validate_physics_version(version: str) -> str:
    if version not in KNOWN_PHYSICS_VERSIONS:
        raise PhysicsVersionError(f"Unknown physics version {version!r}; known: {', '.join(KNOWN_PHYSICS_VERSIONS)}")
    return version


def active_physics_version() -> str:
    """The version used when none is given explicitly: $PHYSICS_VERSION, else PHYSICS_VERSION."""
    raw = os.getenv("PHYSICS_VERSION")
    if raw is None or not raw.strip():
        return PHYSICS_VERSION
    return validate_physics_version(raw.strip())


def assert_same_physics_version(*versions: str | None) -> str:
    """Return the single version shared by ``versions``; raise if they differ or any is unknown/None.

    For reports and aggregates: history is never recomputed, so rows produced by
    different versions must not be combined into one figure.
    """
    if not versions:
        raise PhysicsVersionError("No physics versions given")
    unique = set(versions)
    if None in unique:
        raise PhysicsVersionError("A record has no physics version; refusing to mix it with versioned records")
    if len(unique) != 1:
        raise PhysicsVersionError(f"Refusing to mix physics versions: {sorted(v for v in unique if v)}")
    return validate_physics_version(next(iter(unique)))  # type: ignore[arg-type]


# =============================================================================================
# T19 -- artifact-lineage version constants (contract section 10)
#
# Every constant below is part of what a trained artifact was built against. The ArtifactGate
# (src/artifacts/loaders.py) compares the values recorded in a model's manifest with the values
# defined here, read at call time. Changing ANY of them -- or any physics constant in
# src/digital_twin.py, which feeds ``physics_params_hash`` -- therefore makes every artifact that
# recorded the old value fail the gate until it is retrained or explicitly waived.
#
# Bump a constant in the same change that alters the thing it names:
#   ENV_VERSION               DataCentreEnv dynamics / episode structure (src/optimizer.py)
#   REWARD_VERSION            the reward function and its normalisation constants
#   SAFETY_ENVELOPE_VERSION   the safety limits / violation definition the policy is trained against
#   ACTION_SEMANTICS_VERSION  what an action vector MEANS (ranges, mode mapping), not just its shape
# The observation / action SHAPES are covered separately by their schema hashes.
# =============================================================================================
ENV_VERSION = "1"
REWARD_VERSION = "1"
SAFETY_ENVELOPE_VERSION = "1"
ACTION_SEMANTICS_VERSION = "1"

# Cadence of the telemetry the models consume / the environment steps at (5 minutes). Mirrors
# src/digital_twin.INTERVAL_MINUTES and src/optimizer.INTERVAL_MIN; a test keeps them in step.
INPUT_CADENCE_S = 300

# Declarative schemas. Order matters: it is the order of the vector the policy sees / emits.
OBSERVATION_SCHEMA: dict[str, Any] = {
    "name": "DataCentreEnv.observation",
    "dtype": "float32",
    "shape": [9],
    "low": 0.0,
    "high": 1.0,
    "features": [
        "hour",
        "utilisation",
        "outside_temp",
        "inlet_temp",
        "outlet_temp",
        "it_power",
        "wue",
        "pue",
        "water_stress",
    ],
}
ACTION_SCHEMA: dict[str, Any] = {
    "name": "DataCentreEnv.action",
    "dtype": "float32",
    "shape": [2],
    "low": [0.0, 0.0],
    "high": [1.0, 1.0],
    "components": ["chilled_water_temp_norm", "cooling_mode_norm"],
}

# The compatibility fields of contract 10.2 check 2, in the order they are checked.
COMPAT_FIELDS: tuple[str, ...] = (
    "physics_version",
    "physics_params_hash",
    "environment_version",
    "observation_schema_hash",
    "action_schema_hash",
    "action_semantics_version",
    "reward_version",
    "safety_envelope_version",
    "input_cadence_s",
)


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, NaN/inf rejected."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=True)


def sha256_json(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def observation_schema_hash() -> str:
    return sha256_json(OBSERVATION_SCHEMA)


def action_schema_hash() -> str:
    return sha256_json(ACTION_SCHEMA)


_PHYSICS_CONSTANT_NAME = re.compile(r"^_?[A-Z][A-Z0-9_]*$")
_SCALARS = (bool, int, float, str)


def _hashable_value(value: Any) -> Any:
    """JSON-able form of a physics constant, or raise TypeError if it is not a plain constant."""
    if isinstance(value, enum.Enum):
        return f"{type(value).__name__}.{value.name}"
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, _SCALARS) or value is None:
        return value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _hashable_value(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, (tuple, list)):
        return [_hashable_value(v) for v in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = f"{type(k).__name__}.{k.name}" if isinstance(k, enum.Enum) else str(k)
            out[key] = _hashable_value(v)
        return out
    raise TypeError(type(value).__name__)


def physics_constants(module: Any = None) -> dict[str, Any]:
    """Every UPPER_CASE plain-data constant of src/digital_twin.py, as JSON-able values.

    Discovered rather than listed, so a constant added in a later physics task is covered without
    anyone remembering to register it.
    """
    if module is None:
        from src import digital_twin as module  # lazy: digital_twin imports this module
    found: dict[str, Any] = {}
    for name in sorted(vars(module)):
        if not _PHYSICS_CONSTANT_NAME.match(name):
            continue
        try:
            found[name] = _hashable_value(getattr(module, name))
        except TypeError:
            continue  # classes, functions, loggers, compiled patterns ...: not constants
    return found


def physics_params_hash(version: str | None = None, *, module: Any = None) -> str:
    """Hash of the physics version label plus every physics constant the twin runs with."""
    chosen = validate_physics_version(version) if version is not None else active_physics_version()
    return sha256_json({"physics_version": chosen, "constants": physics_constants(module)})


def running_compat_values() -> dict[str, Any]:
    """The values the running code defines for each compatibility field (read at call time)."""
    return {
        "physics_version": active_physics_version(),
        "physics_params_hash": physics_params_hash(),
        "environment_version": ENV_VERSION,
        "observation_schema_hash": observation_schema_hash(),
        "action_schema_hash": action_schema_hash(),
        "action_semantics_version": ACTION_SEMANTICS_VERSION,
        "reward_version": REWARD_VERSION,
        "safety_envelope_version": SAFETY_ENVELOPE_VERSION,
        "input_cadence_s": INPUT_CADENCE_S,
    }
