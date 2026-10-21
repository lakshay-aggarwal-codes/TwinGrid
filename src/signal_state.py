"""Signal state v1 (Task 16, playbook §8.5): ONE rule for "is this number normal, warning, critical, stale, offline or unknown".

The TypeScript mirror is ``twin-stream-insight-main/src/contract/signalState.ts``; both read
``tests/fixtures/signal_state_cases.json`` and must return identical results for every case.

Precedence (first match wins)
1. no usable value (``None`` or non-finite)  -> ``unknown`` (``no_value``) while connected, ``offline`` (``disconnected``) when not
2. value present but ``observed_at`` missing -> ``unknown`` (``no_value``): freshness cannot be judged, so the number is not shown as current
3. ``observed_at`` ahead of ``now`` by more than ``FUTURE_TOLERANCE_S`` -> ``unknown`` (``future``): a reading from the future
   cannot be current, so no number is shown and ``age_s`` is ``None``. A timestamp ahead by at most the tolerance is ordinary
   clock skew and counts as age 0.
4. ``age_s > stale_after_s``                  -> ``stale`` (``too_old``): the value is kept (it is "last known") together with its age
5. a critical bound crossed                   -> ``critical`` (``above_crit`` / ``below_crit``)
6. a warning bound crossed                    -> ``warning`` (``above_warn`` / ``below_warn``)
7. otherwise                                  -> ``normal`` (``within_bounds``)

A bound is "crossed" only by a STRICT comparison (``value > high`` / ``value < low``), the same convention as
``SafetyEnvelope.violations`` (a value exactly on a limit is inside it). Stale beats critical on purpose: an old number
must never be reported as a current alarm, and never as green.

Rules are DERIVED from existing constants, nothing is invented here: the inlet/outlet/PUE critical bounds are
``SAFETY_ENVELOPE`` (src/digital_twin.py); the staleness window mirrors ``hooks/liveness.ts``. The repository defines no
separate warning band, so the default rules have none (``warn_*`` are ``None``).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

STATUSES = ("normal", "warning", "critical", "stale", "offline", "unknown")
REASON_CODES = (
    "no_value",
    "future",
    "disconnected",
    "too_old",
    "above_crit",
    "below_crit",
    "above_warn",
    "below_warn",
    "within_bounds",
    "rule_unavailable",
)

# Mirror of twin-stream-insight-main/src/hooks/liveness.ts (DEFAULT_INTERVAL_S, STALE_INTERVAL_MULTIPLIER, MIN_STALE_AFTER_MS).
DEFAULT_INTERVAL_S = 3.0
STALE_INTERVAL_MULTIPLIER = 3.0
MIN_STALE_AFTER_S = 5.0
# Clock-skew allowance: a timestamp up to this far ahead of ``now`` is read as "just now" (age 0); further ahead is ``future``.
# Mirrored in twin-stream-insight-main/src/contract/signalState.ts (FUTURE_TOLERANCE_S).
FUTURE_TOLERANCE_S = 5.0


@dataclass(frozen=True)
class SignalRule:
    rule_id: str
    warn_low: float | None = None
    warn_high: float | None = None
    crit_low: float | None = None
    crit_high: float | None = None
    unit: str = ""


@dataclass(frozen=True)
class SignalState:
    status: str
    reason_code: str
    rule_id: str
    value: float | None
    threshold: float | None  # the bound that was crossed (warning / critical); None otherwise
    observed_at: datetime | None
    age_s: float | None
    unit: str

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready: ``observed_at`` as ``YYYY-MM-DDTHH:MM:SS(.ffffff)Z`` (UTC)."""
        out = asdict(self)
        out["observed_at"] = isoformat_z(self.observed_at)
        return out


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _ms(value: datetime) -> int:
    """Whole milliseconds since the epoch (sub-millisecond precision is dropped, as in a JavaScript ``Date``)."""
    return (_utc(value) - _EPOCH) // timedelta(milliseconds=1)


def isoformat_z(value: datetime | None) -> str | None:
    """Canonical UTC text shared with the TypeScript mirror: ``YYYY-MM-DDTHH:MM:SS`` + ``.fff`` only if the millisecond part is non-zero + ``Z``."""
    if value is None:
        return None
    ms = _ms(value)
    base = (_EPOCH + timedelta(milliseconds=ms)).strftime("%Y-%m-%dT%H:%M:%S")
    frac = ms % 1000
    return f"{base}.{frac:03d}Z" if frac else f"{base}Z"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("signal timestamps must be timezone-aware (UTC)")
    return value.astimezone(timezone.utc)


def stale_after_s(interval_s: float | None = None) -> float:
    """Stale window in seconds for a feed that ticks every ``interval_s`` wall seconds (same formula as the browser)."""
    s = (
        interval_s
        if isinstance(interval_s, (int, float)) and math.isfinite(interval_s) and interval_s > 0
        else DEFAULT_INTERVAL_S
    )
    return max(MIN_STALE_AFTER_S, float(s) * STALE_INTERVAL_MULTIPLIER)


def evaluate(
    value: float | None,
    observed_at: datetime | None,
    now: datetime,
    rule: SignalRule,
    stale_after_s: float,  # noqa: F811 - the parameter name is the §8.5 contract
    connected: bool = True,
) -> SignalState:
    """Classify one reading. Pure: no clock, no I/O. ``now`` and ``observed_at`` must be timezone-aware."""
    usable = value is not None and math.isfinite(value)
    obs = _utc(observed_at) if observed_at is not None else None
    age: float | None = None
    future = False
    if obs is not None:
        delta_ms = _ms(now) - _ms(obs)  # whole ms, like the browser
        future = -delta_ms > FUTURE_TOLERANCE_S * 1000  # strictly beyond the skew allowance
        if not future:
            age = max(0, delta_ms) / 1000  # skew inside the allowance is age 0, not stale

    def state(status: str, reason: str, *, keep_value: bool, threshold: float | None = None) -> SignalState:
        return SignalState(
            status=status,
            reason_code=reason,
            rule_id=rule.rule_id,
            value=float(value) if keep_value and usable and value is not None else None,
            threshold=threshold,
            observed_at=obs,
            age_s=age,
            unit=rule.unit,
        )

    if not usable:
        return (
            state("unknown", "no_value", keep_value=False)
            if connected
            else state("offline", "disconnected", keep_value=False)
        )
    assert value is not None
    if obs is None:
        return state("unknown", "no_value", keep_value=False)
    if future:
        return state("unknown", "future", keep_value=False)
    if age is not None and age > stale_after_s:
        return state("stale", "too_old", keep_value=True)
    if rule.crit_high is not None and value > rule.crit_high:
        return state("critical", "above_crit", keep_value=True, threshold=rule.crit_high)
    if rule.crit_low is not None and value < rule.crit_low:
        return state("critical", "below_crit", keep_value=True, threshold=rule.crit_low)
    if rule.warn_high is not None and value > rule.warn_high:
        return state("warning", "above_warn", keep_value=True, threshold=rule.warn_high)
    if rule.warn_low is not None and value < rule.warn_low:
        return state("warning", "below_warn", keep_value=True, threshold=rule.warn_low)
    return state("normal", "within_bounds", keep_value=True)


def unavailable(rule_id: str, unit: str = "") -> SignalState:
    """What a caller returns when no rule exists for a signal: ``unknown`` / ``rule_unavailable``, never a guess."""
    return SignalState("unknown", "rule_unavailable", rule_id, None, None, None, None, unit)


def default_rules() -> dict[str, SignalRule]:
    """Rules derived from ``SAFETY_ENVELOPE`` (imported lazily: ``src.digital_twin`` pulls numpy/pandas)."""
    from .digital_twin import SAFETY_ENVELOPE as env

    return {
        "inlet_temp_c": SignalRule("inlet_temp_c", crit_low=env.inlet_min_C, crit_high=env.inlet_max_C, unit="°C"),
        "outlet_temp_c": SignalRule("outlet_temp_c", crit_high=env.outlet_max_C, unit="°C"),
        "pue": SignalRule("pue", crit_high=env.pue_max, unit=""),
    }


def rule_for(signal: str) -> SignalRule | None:
    return default_rules().get(signal)
