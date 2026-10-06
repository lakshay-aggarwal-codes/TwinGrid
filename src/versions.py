"""Physics version registry.

Every number the digital twin produces comes from one named physics version, so
results from different versions are never silently mixed and an old version can
still be replayed.

* ``legacy-0``  the original equations, frozen. Selectable for replay and for
  the golden tests; its numerics are bit-identical to the pre-versioning code.
* ``1``         Physics v1: energy closure, a latent-heat water bound, finite
  cooling capacity, validated inputs, one carbon definition, one safety envelope
  and a reachable inlet band. See src/digital_twin.py.
* ``2``         Physics v2 ("dynamic twin", uncalibrated): explicit thermal-energy and
  actuator state (lumped capacitance), a frozen hashable ``PhysicsParams``.
  See src/physics/ and docs/PHYSICS_V2.md. Opt-in: the default stays ``1``;
  roll back with ``PHYSICS_VERSION=1``. A v2 result is identified by the PAIR
  (version, ``physics_params_hash``) -- see ``physics_identity``.

Selection: ``DigitalTwin(physics_version=...)`` wins; otherwise the
``PHYSICS_VERSION`` environment variable; otherwise ``PHYSICS_VERSION`` below.
The environment is read on every call (not at import) so a deployment or a test
can switch without a reload. An unknown value raises: it never falls back.
"""

from __future__ import annotations

import os

LEGACY_PHYSICS_VERSION = "legacy-0"
PHYSICS_V1 = "1"
PHYSICS_V2 = "2"
KNOWN_PHYSICS_VERSIONS: tuple[str, ...] = (LEGACY_PHYSICS_VERSION, PHYSICS_V1, PHYSICS_V2)

# The version new work is done under. Deliberately still v1: v2 is selected explicitly
# (DigitalTwin(physics_version="2") or PHYSICS_VERSION=2) until the default is changed on purpose.
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


def physics_identity(version: str, params: "object | None" = None) -> dict[str, str | None]:
    """The identity a result/manifest must carry: ``{"physics_version", "physics_params_hash"}``.

    Versions without a parameter surface (``legacy-0``, ``1``) have ``physics_params_hash`` None. Version
    ``2`` REQUIRES its ``PhysicsParams`` (anything with ``params_hash()``): two v2 runs with different
    parameters are different physics and must never be combined.
    """
    validate_physics_version(version)
    if version != PHYSICS_V2:
        if params is not None:
            raise PhysicsVersionError(f"physics version {version!r} has no parameter surface; got params")
        return {"physics_version": version, "physics_params_hash": None}
    if params is None or not hasattr(params, "params_hash"):
        raise PhysicsVersionError("physics version '2' requires PhysicsParams (its hash is part of the identity)")
    return {"physics_version": version, "physics_params_hash": params.params_hash()}  # type: ignore[attr-defined]


def assert_same_physics_identity(*identities: "dict[str, str | None] | None") -> dict[str, str | None]:
    """Like ``assert_same_physics_version`` but also refuses different ``physics_params_hash`` values, and a
    v2 record without a hash. Returns the single shared identity."""
    if not identities:
        raise PhysicsVersionError("No physics identities given")
    if any(i is None for i in identities):
        raise PhysicsVersionError("A record has no physics identity; refusing to mix it with identified records")
    version = assert_same_physics_version(*(i.get("physics_version") for i in identities))  # type: ignore[union-attr]
    hashes = {i.get("physics_params_hash") for i in identities}  # type: ignore[union-attr]
    if version == PHYSICS_V2 and (None in hashes or "" in hashes):
        raise PhysicsVersionError("A physics-v2 record has no physics_params_hash")
    if len(hashes) != 1:
        raise PhysicsVersionError(f"Refusing to mix physics parameter sets: {sorted(str(h) for h in hashes)}")
    return {"physics_version": version, "physics_params_hash": next(iter(hashes))}
