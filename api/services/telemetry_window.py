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

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

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
