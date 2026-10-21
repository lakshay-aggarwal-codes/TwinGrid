"""``signal_status``: the playbook 8.5 ``SignalState`` shape, from ``src/signal_state.evaluate`` (Task 16).

When no rule exists for a signal, or the rule cannot be evaluated, the status is ``unknown`` with reason code
``rule_unavailable``: the adapter never invents a state, and in particular never answers ``normal`` without a rule.
(Integration: the ``ImportError`` fallback that stood in for a missing ``src/signal_state.py`` is removed now that
Task 16 is merged.)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from src.signal_state import SignalRule, evaluate

from . import evidence

RULE_FIELDS = ("warn_low", "warn_high", "crit_low", "crit_high")


def _unknown(
    rule: Mapping[str, Any] | None, value: float | None, observed_at: datetime | None, now: datetime, unit: str | None
) -> dict[str, Any]:
    return {
        "status": "unknown",
        "reason_code": "rule_unavailable",
        "rule_id": (rule or {}).get("rule_id"),
        "value": value,
        "threshold": None,
        "observed_at": evidence.iso_utc(observed_at),
        "age_s": evidence.age_seconds(observed_at, now),
        "unit": unit,
    }


def signal_status(
    *,
    value: float | None,
    observed_at: datetime | None,
    now: datetime,
    rule: Mapping[str, Any] | None,
    stale_after_s: int,
    connected: bool = True,
    unit: str | None = None,
) -> dict[str, Any]:
    """The section 8.5 shape: ``status, reason_code, rule_id, value, threshold, observed_at, age_s, unit``."""
    if rule is None:
        return _unknown(rule, value, observed_at, now, unit)
    try:
        state = evaluate(
            value,
            observed_at,
            now,
            SignalRule(rule_id=rule["rule_id"], unit=rule.get("unit", unit), **{k: rule.get(k) for k in RULE_FIELDS}),
            stale_after_s,
            connected,
        )
    except Exception:  # noqa: BLE001 - a rule that cannot be evaluated is "unknown", never an error or a guess
        return _unknown(rule, value, observed_at, now, unit)
    return {
        "status": state.status,
        "reason_code": state.reason_code,
        "rule_id": state.rule_id,
        "value": state.value,
        "threshold": state.threshold,
        "observed_at": evidence.iso_utc(state.observed_at),
        "age_s": state.age_s,
        "unit": state.unit,
    }
