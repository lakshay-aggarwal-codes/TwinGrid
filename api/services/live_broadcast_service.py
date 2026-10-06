"""Server-held telemetry window for the anomaly pipeline (T3).

``TelemetryWindowProvider`` is the INTERFACE the anomaly pipeline depends on:
``window(n)`` returns the last ``n`` server-held samples, oldest first, each carrying
``{seq, ts_ingest, origin, features}``. T3's implementation is an in-memory ring buffer
that ``_tick`` fills; a later task (T10) replaces the implementation, not this interface.

``features`` are the five model inputs in the model's own order (``FEATURE_ORDER``, which
matches ``models/anomaly/config.json`` ``feature_columns``). A sample is whatever the server
itself produced for that tick -- a client can never put data into this window.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence

logger = logging.getLogger(__name__)

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

# Evidence ranking for "lowest-evidence origin in the window". Only "simulated" exists today;
# unknown origins rank above it so a window containing any simulated sample is labelled simulated.
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


# -----------------------------------------------------------------------------
# Store-backed window (T17, roadmap 9.5)
#
# The window is built from STORED samples (``telemetry_sample``, stream ``live``) and is scorable only when it is
# contiguous, valid, single-origin and at the model's cadence. Otherwise the result is ``warming_up`` with a
# ``reason`` and NO score. ``evaluate_window`` is pure (no I/O) so every rule is unit-testable; ``load_store_window``
# does the reads; ``current_window`` picks the source (TELEMETRY_WINDOW_SOURCE).
# -----------------------------------------------------------------------------

LIVE_STREAM = "live"
GAP_FACTOR = 1.5  # a gap is a consecutive difference > GAP_FACTOR * sampling_interval_s
ALIGN_FACTOR = 0.5  # samples of different sensors align when their ts_event differ by <= ALIGN_FACTOR * interval
LOAD_MARGIN = 4  # extra rows read per sensor beyond WINDOW_SIZE so a lagging sensor can still be aligned

REASON_INSUFFICIENT = "insufficient"
REASON_GAP = "gap"
REASON_INVALID_SAMPLE = "invalid_sample"
REASON_MIXED_ORIGIN = "mixed_origin"
REASON_CADENCE_MISMATCH = "cadence_mismatch"
REASONS = (REASON_INSUFFICIENT, REASON_GAP, REASON_INVALID_SAMPLE, REASON_MIXED_ORIGIN, REASON_CADENCE_MISMATCH)


@dataclass(frozen=True)
class StoredPoint:
    """One stored sample of one sensor (any quality)."""

    id: int
    ts_event: datetime
    ts_ingest: datetime
    value: float
    quality: str
    origin: str


@dataclass(frozen=True)
class SensorSeries:
    """The latest stored points of one feature sensor, oldest first."""

    external_id: str
    sampling_interval_s: float
    points: Sequence[StoredPoint]


@dataclass(frozen=True)
class WindowEvaluation:
    """``samples`` is the full window (oldest first) iff ``reason is None``; otherwise it is empty.

    ``filled`` is how many of the latest aligned samples are usable (trailing run that is aligned, valid and
    gap-free); it equals ``WINDOW_SIZE`` exactly when the window is scorable.
    """

    samples: list[TelemetrySample]
    reason: Optional[str]
    filled: int

    @property
    def scorable(self) -> bool:
        return self.reason is None


def _not_scorable(reason: str, filled: int = 0) -> WindowEvaluation:
    return WindowEvaluation([], reason, max(0, min(filled, WINDOW_SIZE - 1)))


def _nearest(points: Sequence[StoredPoint], ts: datetime, tolerance_s: float) -> Optional[StoredPoint]:
    best: Optional[StoredPoint] = None
    best_d = tolerance_s
    for pt in points:
        d = abs((pt.ts_event - ts).total_seconds())
        if d <= best_d:
            best, best_d = pt, d
    return best


def evaluate_window(
    series_by_feature: Mapping[str, Optional[SensorSeries]],
    *,
    cadence_s: float,
    size: int = WINDOW_SIZE,
) -> WindowEvaluation:
    """Apply roadmap 9.5 to the latest stored points of the five feature sensors. Pure.

    Checks run in this order and the first failure decides ``reason``:
    ``insufficient`` (a sensor is unknown or has fewer than ``size`` points, or has no point aligned with a slot
    and too little history), ``cadence_mismatch`` (a sensor's ``sampling_interval_s`` is not ``cadence_s``),
    ``invalid_sample`` (any quality != ok in the window), ``gap`` (a consecutive difference > 1.5 x interval or no
    aligned sample for a slot), ``mixed_origin`` (more than one origin across the window).
    """
    series: dict[str, SensorSeries] = {}
    for feature in FEATURE_ORDER:
        item = series_by_feature.get(feature)
        if item is None or not item.points:
            return _not_scorable(REASON_INSUFFICIENT)
        series[feature] = item

    ref = series[FEATURE_ORDER[0]]
    if len(ref.points) < size:
        return _not_scorable(REASON_INSUFFICIENT, len(ref.points))
    for item in series.values():
        if abs(item.sampling_interval_s - cadence_s) > 1e-9:
            return _not_scorable(REASON_CADENCE_MISMATCH)

    ref_points = list(ref.points)[-size:]
    # Align every sensor to the reference timestamps (oldest first).
    columns: dict[str, list[Optional[StoredPoint]]] = {}
    for feature, item in series.items():
        tolerance = ALIGN_FACTOR * item.sampling_interval_s
        columns[feature] = [
            rp if feature == FEATURE_ORDER[0] else _nearest(item.points, rp.ts_event, tolerance) for rp in ref_points
        ]

    # Trailing usable run (for ``filled``): slot i is usable if every sensor has an ok point there and the step from
    # slot i-1 is not a gap. Counted from the newest slot backwards.
    def slot_ok(i: int) -> bool:
        return all(columns[f][i] is not None and columns[f][i].quality == "ok" for f in FEATURE_ORDER)  # type: ignore[union-attr]

    gap_limit = GAP_FACTOR * ref.sampling_interval_s
    run = 0
    for i in range(size - 1, -1, -1):
        if not slot_ok(i):
            break
        run += 1
        if i > 0 and (ref_points[i].ts_event - ref_points[i - 1].ts_event).total_seconds() > gap_limit:
            break

    # 1. Invalid sample inside the window.
    for f in FEATURE_ORDER:
        for pt in columns[f]:
            if pt is not None and pt.quality != "ok":
                return _not_scorable(REASON_INVALID_SAMPLE, run)
    # 2. Gap: a missing aligned sample, or a consecutive difference > 1.5 x interval in any sensor's own run.
    for f in FEATURE_ORDER:
        col = columns[f]
        if any(pt is None for pt in col):
            return _not_scorable(REASON_GAP, run)
        limit = GAP_FACTOR * series[f].sampling_interval_s
        for a, b in zip(col, col[1:]):
            if (b.ts_event - a.ts_event).total_seconds() > limit:  # type: ignore[union-attr]
                return _not_scorable(REASON_GAP, run)
    # 3. One origin across all 5 x size samples.
    origins = {pt.origin for f in FEATURE_ORDER for pt in columns[f]}  # type: ignore[union-attr]
    if len(origins) != 1:
        return _not_scorable(REASON_MIXED_ORIGIN, run)

    origin = next(iter(origins))
    out: list[TelemetrySample] = []
    for i, rp in enumerate(ref_points):
        row = [columns[f][i] for f in FEATURE_ORDER]
        ingest = max(pt.ts_ingest for pt in row)  # type: ignore[union-attr]
        out.append(
            TelemetrySample(
                seq=rp.id,  # the reference sensor's telemetry_sample.id: strictly increasing per ingest order
                ts_ingest=ingest.isoformat(),
                origin=origin,
                features=tuple(float(pt.value) for pt in row),  # type: ignore[union-attr,arg-type]
            )
        )
    return WindowEvaluation(out, None, size)


def memory_evaluation(provider: Optional[TelemetryWindowProvider] = None, n: int = WINDOW_SIZE) -> WindowEvaluation:
    """The in-process ring buffer as a ``WindowEvaluation`` (rollback source, and what T3 shipped)."""
    samples = (provider or get_window_provider()).window(n)
    if len(samples) < n:
        return WindowEvaluation([], REASON_INSUFFICIENT, len(samples))
    return WindowEvaluation(list(samples), None, n)


async def load_store_series(
    session: Any, *, rows_per_sensor: int = WINDOW_SIZE + LOAD_MARGIN
) -> dict[str, Optional[SensorSeries]]:
    """Read the latest ``rows_per_sensor`` stored ``live`` points (any quality) of each feature sensor."""
    from sqlalchemy import select

    from api import config
    from models.db_models import Sensor
    from models.db_models import TelemetrySample as StoredSample

    mapping = config.telemetry_feature_sensors()
    sensors = {
        s.external_id: s
        for s in (await session.execute(select(Sensor).where(Sensor.external_id.in_(set(mapping.values()))))).scalars()
    }
    out: dict[str, Optional[SensorSeries]] = {}
    for feature in FEATURE_ORDER:
        sensor = sensors.get(mapping[feature])
        if sensor is None:
            out[feature] = None
            continue
        rows = (
            (
                await session.execute(
                    select(StoredSample)
                    .where(StoredSample.sensor_id == sensor.id, StoredSample.stream_id == LIVE_STREAM)
                    .order_by(StoredSample.ts_event.desc(), StoredSample.id.desc())
                    .limit(rows_per_sensor)
                )
            )
            .scalars()
            .all()
        )
        points = [
            StoredPoint(r.id, _aware(r.ts_event), _aware(r.ts_ingest), r.value, r.quality, r.origin)
            for r in reversed(rows)
        ]
        out[feature] = SensorSeries(sensor.external_id, float(sensor.sampling_interval_s), points)
    return out


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes for timezone-aware columns; everything stored here is UTC."""
    from datetime import timezone

    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


async def load_store_window(session: Any, *, cadence_s: Optional[float] = None) -> WindowEvaluation:
    from api import config

    series = await load_store_series(session)
    return evaluate_window(series, cadence_s=config.ANOMALY_INPUT_CADENCE_S if cadence_s is None else cadence_s)


def effective_window_source() -> str:
    """``store`` or ``memory``. With the store switched off nothing is written to it, so the window falls back to
    ``memory`` instead of waiting forever on an empty store."""
    from api import config

    if not config.telemetry_store_enabled():
        return "memory"
    return config.telemetry_window_source()


async def current_window(session_factory: Callable[[], Any]) -> WindowEvaluation:
    """The window the anomaly pipeline should score, from the configured source. A store read failure propagates
    (the caller fails closed to ``status=error``); it is never replaced by the in-memory window."""
    if effective_window_source() == "memory":
        return memory_evaluation()
    async with session_factory() as session:
        return await load_store_window(session)
