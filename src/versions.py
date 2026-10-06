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

import os

LEGACY_PHYSICS_VERSION = "legacy-0"
PHYSICS_V1 = "1"
KNOWN_PHYSICS_VERSIONS: tuple[str, ...] = (LEGACY_PHYSICS_VERSION, PHYSICS_V1)

# The version new work is done under.
PHYSICS_VERSION = PHYSICS_V1

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
