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
PHYSICS_V2 = "2"  # RECONSTRUCTED
KNOWN_PHYSICS_VERSIONS: tuple[str, ...] = (LEGACY_PHYSICS_VERSION, PHYSICS_V1, PHYSICS_V2)  # RECONSTRUCTED

# The version new work is done under.
PHYSICS_VERSION = PHYSICS_V1

# Provenance label for a reading produced by the simulator (sensor_readings.origin; migration M1 default).
ORIGIN_SIMULATED = "simulated"

# Version of THE safety envelope definition (src.digital_twin.SAFETY_ENVELOPE) and of every consumer that
# must agree with it (twin ``is_safe``, the RL safety penalty, the optimizer's violation count).
#   "1"  (implicit, never recorded) outlet-only penalty/violation count; inlet and PUE were not checked
#        by the optimizer; the v1 action range could not reach the inlet band.
#   "2"  one envelope (inlet, outlet, PUE) drives penalty and violation count; the v1 chilled-water action
#        range is derived from the envelope; carbon reward term uses ``carbon_emissions_gco2``.
# Bump this string whenever any envelope limit or any consumer's use of it changes. An artifact (trained
# policy, manifest) records the value it was produced under; one with an older or missing value is rejected.
SAFETY_ENVELOPE_VERSION = "2"


class SafetyEnvelopeVersionError(ValueError):
    """An artifact was produced under a different (older) safety-envelope definition."""


def assert_current_safety_envelope_version(recorded: object) -> str:
    """Return ``recorded`` if it equals ``SAFETY_ENVELOPE_VERSION``; raise otherwise (missing == older)."""
    if recorded != SAFETY_ENVELOPE_VERSION:
        raise SafetyEnvelopeVersionError(
            f"artifact safety_envelope_version={recorded!r} but the current envelope is "
            f"{SAFETY_ENVELOPE_VERSION!r}; retrain or re-evaluate under the current envelope"
        )
    return SAFETY_ENVELOPE_VERSION


# ----------------------------------------------------------------------------------------------
# Environment contract (T27, roadmap 13.5). Every trained artifact records these; the loader rejects
# any artifact whose values differ (a missing value == a pre-v2 artifact).
#   ENV_VERSION  "2"  observation = base state + applied actuator state + previous executed action +
#                     room-thermal state; the shield is part of the environment; ``info`` reports what
#                     was executed. (pre-v2 environments had 9 features, no shield, no action report.)
#   ACTION_SEMANTICS_VERSION "2"  a_s (sampled) -> a_e = clip(a_s, 0, 1) (SB3) -> shield(state, a_e) = a_x
#                     executed; the PPO buffer keeps a_s. ("1": the drought override was applied inside
#                     the env's action decoding and not reported.)
#   REWARD_VERSION "2"  -J with the SafetyEnvelope penalty and the single carbon function (T20).
#   SHIELD_VERSION "1"  the pure ``shield`` in src/rl/safety_filter.py (drought rule, sanitising).
# Bump the string whenever the behaviour it names changes.
# ----------------------------------------------------------------------------------------------
ENV_VERSION = "2"
ACTION_SEMANTICS_VERSION = "2"
REWARD_VERSION = "2"
SHIELD_VERSION = "1"

CURRENT_ENV_VERSIONS: dict[str, str] = {
    "env_version": ENV_VERSION,
    "action_semantics_version": ACTION_SEMANTICS_VERSION,
    "reward_version": REWARD_VERSION,
    "shield_version": SHIELD_VERSION,
    "safety_envelope_version": SAFETY_ENVELOPE_VERSION,
}


class EnvContractError(ValueError):
    """An artifact was produced under a different (older) environment contract."""


def assert_current_env_versions(recorded: object) -> dict[str, str]:
    """Return ``recorded`` if every version string equals the current one; raise otherwise.

    ``recorded`` is the artifact's ``env_contract`` mapping; None / missing keys == a pre-v2 artifact.
    """
    if not isinstance(recorded, dict):
        raise EnvContractError("artifact records no env_contract: it predates environment v2 and is rejected")
    wrong = {k: (recorded.get(k), want) for k, want in CURRENT_ENV_VERSIONS.items() if recorded.get(k) != want}
    if wrong:
        detail = ", ".join(f"{k}: artifact={got!r} current={want!r}" for k, (got, want) in sorted(wrong.items()))
        raise EnvContractError(f"artifact environment contract differs from the current one ({detail})")
    return dict(recorded)


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


def physics_identity(version: str, params: "object | None" = None) -> dict[str, str | None]:  # RECONSTRUCTED
    """The identity a result/manifest must carry: ``{"physics_version", "physics_params_hash"}``.  # RECONSTRUCTED
                                                                                                    # RECONSTRUCTED
    Versions without a parameter surface (``legacy-0``, ``1``) have ``physics_params_hash`` None. Version  # RECONSTRUCTED
    ``2`` REQUIRES its ``PhysicsParams`` (anything with ``params_hash()``): two v2 runs with different  # RECONSTRUCTED
    parameters are different physics and must never be combined.  # RECONSTRUCTED
    """  # RECONSTRUCTED
    validate_physics_version(version)  # RECONSTRUCTED
    if version != PHYSICS_V2:  # RECONSTRUCTED
        if params is not None:  # RECONSTRUCTED
            raise PhysicsVersionError(
                f"physics version {version!r} has no parameter surface; got params"
            )  # RECONSTRUCTED
        return {"physics_version": version, "physics_params_hash": None}  # RECONSTRUCTED
    if params is None or not hasattr(params, "params_hash"):  # RECONSTRUCTED
        raise PhysicsVersionError(
            "physics version '2' requires PhysicsParams (its hash is part of the identity)"
        )  # RECONSTRUCTED
    return {"physics_version": version, "physics_params_hash": params.params_hash()}  # type: ignore[attr-defined]  # RECONSTRUCTED


def assert_same_physics_identity(*identities: "dict[str, str | None] | None") -> dict[str, str | None]:  # RECONSTRUCTED
    """Like ``assert_same_physics_version`` but also refuses different ``physics_params_hash`` values, and a  # RECONSTRUCTED
    v2 record without a hash. Returns the single shared identity."""  # RECONSTRUCTED
    if not identities:  # RECONSTRUCTED
        raise PhysicsVersionError("No physics identities given")  # RECONSTRUCTED
    if any(i is None for i in identities):  # RECONSTRUCTED
        raise PhysicsVersionError(
            "A record has no physics identity; refusing to mix it with identified records"
        )  # RECONSTRUCTED
    version = assert_same_physics_version(*(i.get("physics_version") for i in identities))  # type: ignore[union-attr]  # RECONSTRUCTED
    hashes = {i.get("physics_params_hash") for i in identities}  # type: ignore[union-attr]  # RECONSTRUCTED
    if version == PHYSICS_V2 and (None in hashes or "" in hashes):  # RECONSTRUCTED
        raise PhysicsVersionError("A physics-v2 record has no physics_params_hash")  # RECONSTRUCTED
    if len(hashes) != 1:  # RECONSTRUCTED
        raise PhysicsVersionError(
            f"Refusing to mix physics parameter sets: {sorted(str(h) for h in hashes)}"
        )  # RECONSTRUCTED
    return {"physics_version": version, "physics_params_hash": next(iter(hashes))}  # RECONSTRUCTED


# ----------------------------------------------------------------------------------------------
# Artifact compatibility (T19, restored). An artifact records these nine values; the loader and the registry
# compare them with the RUNNING values and reject any difference. ``None`` never equals anything, so a value this
# tree cannot determine makes the check fail closed.
# ----------------------------------------------------------------------------------------------
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

# Seconds of simulated time per model input step (src.digital_twin.INTERVAL_MINUTES * 60).
INPUT_CADENCE_S = 300


def sha256_json(obj: object) -> str:
    """SHA-256 (hex) of the compact, key-sorted, ASCII JSON of ``obj``. Verified against the ``training_config``
    hashes recorded in models/registry.json."""
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


_PHYSICS_CONSTANT_NAME = re.compile(r"^_?[A-Z][A-Z0-9_]*$")
# Version LABELS that digital_twin imports for dispatch. PHYSICS_V2 is left out so that adding the v2 label did not
# change the physics-v1 hash: this reproduces ``physics_params_hash`` recorded by the T29 candidates and baselines.
_PHYSICS_CONSTANT_EXCLUDED = frozenset({"PHYSICS_V2"})


def _hashable_value(value: Any) -> Any:
    """JSON-able form of a physics constant, or raise TypeError if it is not a plain constant."""
    if isinstance(value, enum.Enum):
        return f"{type(value).__name__}.{value.name}"
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, (bool, int, str)) or value is None:
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
    """Every UPPER_CASE plain-data constant of src/digital_twin.py, as JSON-able values (discovered, not listed)."""
    if module is None:
        from src import digital_twin as module  # lazy: digital_twin imports this module
    found: dict[str, Any] = {}
    for name in sorted(vars(module)):
        if not _PHYSICS_CONSTANT_NAME.match(name) or name in _PHYSICS_CONSTANT_EXCLUDED:
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


def running_compat_values() -> dict[str, object]:
    """The running system's value for every field in ``COMPAT_FIELDS`` (read at call time).

    The schema hashes come from src/rl/env.py (imported lazily: it imports this module). A value that cannot be
    computed is ``None``, which never equals anything, so every check fails closed.
    """
    pv = active_physics_version()
    values: dict[str, object] = {
        "physics_version": pv,
        "physics_params_hash": None,
        "environment_version": ENV_VERSION,
        "observation_schema_hash": None,
        "action_schema_hash": None,
        "action_semantics_version": ACTION_SEMANTICS_VERSION,
        "reward_version": REWARD_VERSION,
        "safety_envelope_version": SAFETY_ENVELOPE_VERSION,
        "input_cadence_s": INPUT_CADENCE_S,
    }
    try:
        values["physics_params_hash"] = physics_params_hash(pv)
    except Exception:  # noqa: BLE001
        pass
    try:
        from src.rl import env as _env

        values["observation_schema_hash"] = _env.observation_schema_hash(pv)
        values["action_schema_hash"] = _env.action_schema_hash()
    except Exception:  # noqa: BLE001
        pass
    return values
