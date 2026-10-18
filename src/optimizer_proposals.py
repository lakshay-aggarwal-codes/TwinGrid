"""Optimizer proposals (Task 19): the approval rules and the predicted-effect arithmetic. Pure: no database, no clock.

A proposal is a RECORDED REQUEST: "set the chilled-water setpoint to X and the cooling mode to Y". An operator (or an
admin) proposes; a DIFFERENT admin approves or rejects. Approval is a recorded decision only: TwinGrid applies nothing
to any equipment, and the predicted effect is a twin simulation, not a measurement.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
STATUSES: tuple[str, ...] = (PENDING, APPROVED, REJECTED)

DECISIONS: Mapping[str, str] = {"approve": APPROVED, "reject": REJECTED}

# LEGACY-0 actuator range, kept for backward compatibility. It is NOT the range of the physics the API twin runs by
# default (physics 1: 16..25 C). Use ``actuator_range_C`` / ``accepted_chilled_range_C`` / ``setpoint_check``.
CHILLED_MIN_C = 5.0
CHILLED_MAX_C = 15.0
MAX_NOTE_CHARS = 500

PREDICTION_LABEL = "model estimate on simulated data"
APPROVAL_LABEL = "A decision is recorded only. TwinGrid does not apply setpoints to any equipment."


class DecisionError(ValueError):
    """The decision cannot be recorded. ``code`` is client-safe: ``not_pending`` or ``self_decision``."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def check_decision(status: str, proposer: str, decider: str) -> None:
    """Only a pending proposal can be decided, and never by the person who made it (separation of duties)."""
    if status != PENDING:
        raise DecisionError("not_pending")
    if proposer == decider:
        raise DecisionError("self_decision")


def can_propose(role: str | None) -> bool:
    return role in ("operator", "admin")


def can_decide(role: str | None) -> bool:
    return role == "admin"


def actuator_range_C(physics_version: str | None = None) -> tuple[float, float]:
    """(lowest, highest) chilled-water set-point in C the controllers were evaluated at, under ``physics_version``.

    ``None`` -> the physics the API twin runs (``versions.active_physics_version()``, which ``DigitalTwin()`` also uses).
    Imported lazily so this rules module stays light until a range is needed.
    """
    from src.baselines.policies import actuator_range_C as _range
    from src.versions import active_physics_version

    return _range(physics_version if physics_version is not None else active_physics_version())


def accepted_chilled_range_C(
    registry_bounds: tuple[float, float], physics_version: str | None = None
) -> tuple[float, float]:
    """The set-points the API accepts: the union of the registry's bounds and the evaluated actuator range.

    A SUPERSET of both on purpose: every request that was accepted before still is, and the baseline's own
    recommendation (16..25 C under physics 1) can always be proposed. ``setpoint_check`` says which side of the
    evaluated range a value is on.
    """
    lo, hi = actuator_range_C(physics_version)
    return min(float(registry_bounds[0]), lo), max(float(registry_bounds[1]), hi)


def setpoint_check(proposed_c: float, reference_c: float, physics_version: str | None = None) -> dict[str, Any]:
    """Additive payload: is each set-point inside the range the evaluated controllers could command?

    Outside it the twin still simulates the value, but no controller was evaluated there, and under physics 1 the
    inlet leaves the safety envelope's band (the evaluation treats that as a hard-constraint violation).
    """
    from src.versions import active_physics_version

    physics = physics_version if physics_version is not None else active_physics_version()
    lo, hi = actuator_range_C(physics)
    return {
        "physics_version": physics,
        "actuator_range_C": [lo, hi],
        "proposed_within_actuator_range": lo <= float(proposed_c) <= hi,
        "reference_within_actuator_range": lo <= float(reference_c) <= hi,
    }


_METRICS = ("mean_pue", "total_energy_kwh", "total_co2_kg", "max_outlet_temp_C")


def predicted_effect(
    reference: Mapping[str, Any], proposed: Mapping[str, Any], outlet_limit_c: float
) -> dict[str, Any]:
    """Reference (the current settings) vs proposed, from two twin runs. ``delta = proposed - reference``.

    ``thermal_margin_C`` is the outlet limit minus the run's hottest outlet; ``within_outlet_limit`` is False when the
    proposed run exceeds the limit (such a proposal is refused by the API). Carbon is flagged when either run used the
    flat fallback intensity instead of a real series.
    """
    ref = {k: float(reference[k]) for k in _METRICS}
    new = {k: float(proposed[k]) for k in _METRICS}
    for side in (ref, new):
        side["thermal_margin_C"] = float(outlet_limit_c) - side["max_outlet_temp_C"]
    keys = (*_METRICS, "thermal_margin_C")
    return {
        "label": PREDICTION_LABEL,
        "hours": reference.get("hours"),
        "reference": ref,
        "proposed": new,
        "delta": {k: new[k] - ref[k] for k in keys},
        "outlet_limit_C": float(outlet_limit_c),
        "within_outlet_limit": new["max_outlet_temp_C"] <= float(outlet_limit_c),
        "carbon_data_is_real": bool(reference.get("carbon_data_is_real")) and bool(proposed.get("carbon_data_is_real")),
    }
