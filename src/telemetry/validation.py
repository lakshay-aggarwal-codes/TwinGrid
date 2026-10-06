"""Pure per-sample validation for ``ingest_samples`` (roadmap §9.3 rules 2-5). No I/O, no database.

Outcomes are strings so they can be counted and exported as Prometheus labels.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional

from src.timeutil import TimeContractError, parse_timestamp

# Per-sample outcomes (result counts are keyed by these).
ACCEPTED = "accepted"  # stored, quality ok
INVALID_FUTURE = "invalid_future"  # stored, quality invalid / future
INVALID_RANGE = "invalid_range"  # stored, quality invalid / range
DUPLICATE = "duplicate"  # identical value already stored; no row
CONFLICT = "conflict"  # different value at the same key; first write kept; no row
UNKNOWN_SENSOR = "unknown_sensor"  # rejected
INVALID_TIME = "invalid_time"  # rejected
UNIT_MISMATCH = "unit_mismatch"  # rejected
INVALID_VALUE = "invalid_value"  # rejected

OUTCOMES = (
    ACCEPTED,
    INVALID_FUTURE,
    INVALID_RANGE,
    DUPLICATE,
    CONFLICT,
    UNKNOWN_SENSOR,
    INVALID_TIME,
    UNIT_MISMATCH,
    INVALID_VALUE,
)
REJECTED = frozenset({UNKNOWN_SENSOR, INVALID_TIME, UNIT_MISMATCH, INVALID_VALUE})

FUTURE_TOLERANCE = timedelta(seconds=5)
MAX_BATCH = 1000
ORIGINS = ("simulated", "measured", "replay")

_STREAM_RE = re.compile(
    r"^(live"
    r"|replay:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|import:[A-Za-z0-9._-]+)$"
)


def validate_stream_id(stream_id: Any) -> str:
    """``live`` | ``replay:<uuid>`` | ``import:<dataset_id>`` (<= 64 chars). Raises ValueError otherwise."""
    if not isinstance(stream_id, str) or len(stream_id) > 64 or not _STREAM_RE.match(stream_id):
        raise ValueError(f"invalid stream_id {stream_id!r}: expected 'live', 'replay:<uuid>' or 'import:<dataset_id>'")
    return stream_id


def validate_origin(origin: Any) -> str:
    if origin not in ORIGINS:
        raise ValueError(f"origin must be one of {ORIGINS} (no default), got {origin!r}")
    return origin


@dataclass(frozen=True)
class SensorSpec:
    """The sensor attributes validation needs (decoupled from the ORM row)."""

    id: int
    unit: str
    source_tz: str = "UTC"
    min_valid: Optional[float] = None
    max_valid: Optional[float] = None


@dataclass(frozen=True)
class Validated:
    """Outcome of validating one sample. ``outcome`` is ACCEPTED/INVALID_* (storable) or a rejection."""

    outcome: str
    ts_event: Optional[datetime] = None
    value: Optional[float] = None
    quality: Optional[str] = None
    invalid_reason: Optional[str] = None
    sim_time: Optional[datetime] = None
    detail: str = ""

    @property
    def storable(self) -> bool:
        return self.outcome in (ACCEPTED, INVALID_FUTURE, INVALID_RANGE)


def _reject(outcome: str, detail: str) -> Validated:
    return Validated(outcome=outcome, detail=detail)


def validate_sample(
    sample: Mapping[str, Any],
    sensor: SensorSpec,
    *,
    origin: str,
    ts_ingest: datetime,
    naive_policy: str = "reject",
) -> Validated:
    """Apply §9.3 rules 2-5 to one sample for an already-resolved sensor.

    ``naive_policy``: ``"reject"`` (default) -> a naive ``ts_event`` is ``invalid_time`` unless the sample
    carries its own ``source_tz``; ``"sensor_tz"`` -> a naive ``ts_event`` is read in ``sensor.source_tz``.
    """
    # rule 2: timestamp via §9.2
    raw_ts = sample.get("ts_event")
    tz = sample.get("source_tz")
    if tz is None and naive_policy == "sensor_tz":
        tz = sensor.source_tz
    try:
        ts_event = parse_timestamp(raw_ts, tz)
    except TimeContractError as exc:
        return _reject(INVALID_TIME, str(exc))

    sim_time: Optional[datetime] = None
    raw_sim = sample.get("sim_time")
    if origin == "simulated":
        if raw_sim is None:
            return _reject(INVALID_TIME, "origin 'simulated' requires sim_time")
        try:
            sim_time = parse_timestamp(raw_sim, tz)
        except TimeContractError as exc:
            return _reject(INVALID_TIME, f"sim_time: {exc}")
    elif raw_sim is not None:
        return _reject(INVALID_TIME, f"sim_time is only allowed when origin='simulated' (origin={origin!r})")

    # rule 3: unit must match exactly (no silent conversion)
    unit = sample.get("unit")
    if unit is not None and unit != sensor.unit:
        return _reject(UNIT_MISMATCH, f"unit {unit!r} != sensor unit {sensor.unit!r}")

    # rule 4: finite numbers only (bool is not a measurement)
    raw_value = sample.get("value")
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        return _reject(INVALID_VALUE, f"value must be a finite number, got {type(raw_value).__name__}")
    try:
        value = float(raw_value)
    except OverflowError:
        return _reject(INVALID_VALUE, "value out of float range")
    if not math.isfinite(value):
        return _reject(INVALID_VALUE, "value is NaN or infinite")

    # rule 5: future first, then range; both are stored as invalid
    if ts_event > ts_ingest + FUTURE_TOLERANCE:
        return Validated(INVALID_FUTURE, ts_event, value, "invalid", "future", sim_time)
    if (sensor.min_valid is not None and value < sensor.min_valid) or (
        sensor.max_valid is not None and value > sensor.max_valid
    ):
        return Validated(INVALID_RANGE, ts_event, value, "invalid", "range", sim_time)
    return Validated(ACCEPTED, ts_event, value, "ok", None, sim_time)
