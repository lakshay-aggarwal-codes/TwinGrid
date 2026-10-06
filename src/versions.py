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
