"""Telemetry window for the anomaly pipeline (T3 interface, T17 store-backed source).

``TelemetryWindowProvider`` is the in-memory INTERFACE the pipeline started with: ``window(n)`` returns the
last ``n`` server-held samples, oldest first, each carrying ``{seq, ts_ingest, origin, features}``. It stays
as the ``TELEMETRY_WINDOW_SOURCE=memory`` rollback source.

T17 (roadmap 9.5) builds the window from STORED samples instead (the default, ``store``), so it survives a
restart and can never contain data a client put there. A window is *scorable* only when all of these hold:

* the latest ``WINDOW_SIZE`` (12) samples of the reference sensor each have an aligned sample (within half a
  sampling interval) from every other feature sensor -- otherwise ``gap``;
* consecutive reference samples are at most ``GAP_FACTOR`` (1.5) x the sampling interval apart -- otherwise ``gap``;
* every sample in it has ``quality = ok`` -- otherwise ``invalid_sample``;
* all samples share one origin -- otherwise ``mixed_origin``;
* every feature sensor's sampling interval equals the model cadence -- otherwise ``cadence_mismatch``.

Fewer than 12 reference samples (or a missing feature sensor) is ``insufficient``. Only the ``live`` stream is
read, so replayed / imported / backfilled samples never feed the window. ``filled`` is the length of the
trailing run of contiguous, aligned, valid samples (0..12): how much of the window is already trustworthy.

``features`` are the five model inputs in the model's own order (``FEATURE_ORDER``, which matches
``models/anomaly/config.json`` ``feature_columns``).
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence

from api import config
from src.versions import INPUT_CADENCE_S

# Order the anomaly model was trained with (models/anomaly/config.json: feature_columns).
FEATURE_ORDER: tuple[str, ...] = (
    "water_flow_lpm",
    "water_pressure_bar",
    "server_outlet_temp_C",
    "it_power_kw",
    "humidity_pct",
)
WINDOW_SIZE = 12  # the detector's seq_len
DEFAULT_CAPACITY = 64

GAP_FACTOR = 1.5  # a step larger than GAP_FACTOR x sampling_interval_s is a gap (also used by the read API)
ALIGN_TOLERANCE_FACTOR = 0.5  # partner samples must be within this x sampling_interval_s of the reference sample
MODEL_CADENCE_S = float(INPUT_CADENCE_S)  # the cadence the detector was trained at
LIVE_STREAM = "live"
_FETCH_PER_SENSOR = 3 * WINDOW_SIZE  # newest rows read per sensor: the window plus slack for late partners

# Why a window was not scored. The message of a warming_up status carries one of these.
REASON_INSUFFICIENT = "insufficient"
REASON_GAP = "gap"
REASON_INVALID_SAMPLE = "invalid_sample"
REASON_MIXED_ORIGIN = "mixed_origin"
REASON_CADENCE_MISMATCH = "cadence_mismatch"

# Evidence ranking for "lowest-evidence origin in the window". Unknown origins rank above "simulated" so a
# window containing any simulated sample is labelled simulated.
_ORIGIN_RANK = {"simulated": 0}


@dataclass(frozen=True)
class TelemetrySample:
    seq: int
    ts_ingest: str  # aware-UTC ISO-8601, wall clock at ingest
    origin: str
    features: tuple[float, float, float, float, float]


class TelemetryWindowProvider(Protocol):
    def append(self, sample: TelemetrySample) -> None: ...

    def window(self, n: int = WINDOW_SIZE) -> list[TelemetrySample]:
        """The last ``n`` samples, oldest first. Fewer than ``n`` if not enough exist yet."""
        ...

    def clear(self) -> None: ...


def sample_from_state(state: Mapping[str, Any], *, seq: int, ts_ingest: str, origin: str) -> TelemetrySample:
    """Build a sample from a twin state dict; raises KeyError if a model feature is missing."""
    return TelemetrySample(
        seq=seq,
        ts_ingest=ts_ingest,
        origin=origin,
        features=tuple(float(state[k]) for k in FEATURE_ORDER),  # type: ignore[arg-type]
    )


def lowest_evidence_origin(origins: Sequence[str]) -> str:
    """The weakest-evidence origin present ("simulated" beats everything). Empty -> "unknown"."""
    if not origins:
        return "unknown"
    return min(set(origins), key=lambda o: (_ORIGIN_RANK.get(o, 1), o))


class InMemoryTelemetryWindow:
    """Bounded ring buffer. Appended from the event loop, read from the event loop; ``window``
    returns an immutable copy that is safe to hand to a worker thread."""

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        if capacity < WINDOW_SIZE:
            raise ValueError(f"capacity must be >= {WINDOW_SIZE}")
        self._buf: deque[TelemetrySample] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def append(self, sample: TelemetrySample) -> None:
        with self._lock:
            self._buf.append(sample)

    def window(self, n: int = WINDOW_SIZE) -> list[TelemetrySample]:
        if n <= 0:
            return []
        with self._lock:
            return list(self._buf)[-n:]

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()

    def __len__(self) -> int:
        return len(self._buf)


_provider: TelemetryWindowProvider = InMemoryTelemetryWindow()


def get_window_provider() -> TelemetryWindowProvider:
    return _provider


# --------------------------------------------------------------------------- T17: store-backed window


@dataclass(frozen=True)
class WindowEvaluation:
    """The verdict on the current window: scorable (``samples`` is the 12-sample window) or not (``reason``)."""

    scorable: bool
    reason: Optional[str]
    filled: int
    samples: list[TelemetrySample] = field(default_factory=list)


@dataclass(frozen=True)
class StoredPoint:
    """One stored sample of one sensor (a decoupled view of a ``telemetry_sample`` row)."""

    id: int
    ts_event: datetime
    ts_ingest: datetime
    value: float
    quality: str
    origin: str


@dataclass(frozen=True)
class SensorSeries:
    """The newest stored points of one feature sensor, oldest first."""

    feature: str
    sampling_interval_s: float
    points: Sequence[StoredPoint]


def effective_window_source() -> str:
    """``memory`` when the store is disabled or ``TELEMETRY_WINDOW_SOURCE=memory``; otherwise ``store``."""
    if not config.telemetry_store_enabled():
        return "memory"
    return config.telemetry_window_source()


def _utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes for timezone-aware columns; they are always UTC here."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat()


def _nearest(points: Sequence[StoredPoint], target: datetime, tolerance_s: float) -> Optional[StoredPoint]:
    best: Optional[StoredPoint] = None
    best_d = float("inf")
    for p in points:
        d = abs((_utc(p.ts_event) - target).total_seconds())
        if d <= tolerance_s and d < best_d:
            best, best_d = p, d
    return best


def evaluate_window(series: Mapping[str, SensorSeries], *, cadence_s: float = MODEL_CADENCE_S) -> WindowEvaluation:
    """Decide whether the newest samples of the five feature sensors form a scorable window (pure function)."""
    if any(f not in series for f in FEATURE_ORDER):
        return WindowEvaluation(False, REASON_INSUFFICIENT, 0)
    if any(float(series[f].sampling_interval_s) != float(cadence_s) for f in FEATURE_ORDER):
        return WindowEvaluation(False, REASON_CADENCE_MISMATCH, 0)

    ref = series[FEATURE_ORDER[0]]
    ref_points = sorted(ref.points, key=lambda p: (_utc(p.ts_event), p.id))[-WINDOW_SIZE:]
    interval = float(ref.sampling_interval_s)
    gap_s = GAP_FACTOR * interval
    tolerance_s = ALIGN_TOLERANCE_FACTOR * interval

    # One group per reference sample: its partners (None when a feature has nothing aligned).
    groups: list[Optional[list[StoredPoint]]] = []
    for rp in ref_points:
        target = _utc(rp.ts_event)
        members: list[Optional[StoredPoint]] = []
        for f in FEATURE_ORDER:
            members.append(rp if f == FEATURE_ORDER[0] else _nearest(series[f].points, target, tolerance_s))
        groups.append(None if any(m is None for m in members) else members)  # type: ignore[arg-type]

    def contiguous_with_next(i: int) -> bool:
        return (_utc(ref_points[i + 1].ts_event) - _utc(ref_points[i].ts_event)).total_seconds() <= gap_s

    # filled: trailing run of aligned, valid samples joined by steps no larger than the gap threshold.
    filled = 0
    for i in range(len(ref_points) - 1, -1, -1):
        g = groups[i]
        if g is None or any(m.quality != "ok" for m in g):
            break
        if i < len(ref_points) - 1 and not contiguous_with_next(i):
            break
        filled += 1

    if len(ref_points) < WINDOW_SIZE:
        return WindowEvaluation(False, REASON_INSUFFICIENT, filled)
    if any(g is None for g in groups) or not all(contiguous_with_next(i) for i in range(len(ref_points) - 1)):
        return WindowEvaluation(False, REASON_GAP, filled)
    if any(m.quality != "ok" for g in groups for m in g):  # type: ignore[union-attr]
        return WindowEvaluation(False, REASON_INVALID_SAMPLE, filled)
    origins = {m.origin for g in groups for m in g}  # type: ignore[union-attr]
    if len(origins) > 1:
        return WindowEvaluation(False, REASON_MIXED_ORIGIN, filled)

    samples = [
        TelemetrySample(
            seq=g[0].id,
            ts_ingest=_iso(max(m.ts_ingest for m in g)),
            origin=lowest_evidence_origin([m.origin for m in g]),
            features=tuple(float(m.value) for m in g),  # type: ignore[arg-type]
        )
        for g in groups  # type: ignore[union-attr]
    ]
    return WindowEvaluation(True, None, len(samples), samples)


async def load_store_series(session: Any) -> dict[str, SensorSeries]:
    """The newest ``live``-stream samples of each feature sensor. A feature whose sensor is unknown or retired is omitted."""
    from sqlalchemy import select

    from models import db_models as orm  # the ORM row class shares its name with the in-memory dataclass above

    mapping = config.telemetry_feature_sensors()
    sensors = (
        (
            await session.execute(
                select(orm.Sensor).where(
                    orm.Sensor.external_id.in_(list(mapping.values())), orm.Sensor.retired_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    by_external = {s.external_id: s for s in sensors}
    out: dict[str, SensorSeries] = {}
    for feature in FEATURE_ORDER:
        sensor = by_external.get(mapping[feature])
        if sensor is None:
            continue
        rows = (
            (
                await session.execute(
                    select(orm.TelemetrySample)
                    .where(orm.TelemetrySample.sensor_id == sensor.id, orm.TelemetrySample.stream_id == LIVE_STREAM)
                    .order_by(orm.TelemetrySample.ts_event.desc(), orm.TelemetrySample.id.desc())
                    .limit(_FETCH_PER_SENSOR)
                )
            )
            .scalars()
            .all()
        )
        points = [
            StoredPoint(r.id, _utc(r.ts_event), _utc(r.ts_ingest), r.value, r.quality, r.origin) for r in reversed(rows)
        ]
        out[feature] = SensorSeries(feature, float(sensor.sampling_interval_s), points)
    return out


async def load_store_window(session: Any) -> WindowEvaluation:
    return evaluate_window(await load_store_series(session), cadence_s=MODEL_CADENCE_S)


def _memory_window() -> WindowEvaluation:
    samples = get_window_provider().window(WINDOW_SIZE)
    if len(samples) < WINDOW_SIZE:
        return WindowEvaluation(False, REASON_INSUFFICIENT, len(samples))
    return WindowEvaluation(True, None, len(samples), samples)


async def current_window(session_factory: Callable[[], Any]) -> WindowEvaluation:
    """The window the pipeline should score now. A store read failure PROPAGATES (fail closed): it never
    silently falls back to the in-memory buffer."""
    if effective_window_source() == "memory":
        return _memory_window()
    async with session_factory() as session:
        return await load_store_window(session)
