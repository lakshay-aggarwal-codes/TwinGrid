"""Facility telemetry container, import schema and unit/cadence checks (Task 23).

Rules (from the design):
  * Input is a tidy table: UTC timestamp, channel name from a fixed list, value, unit, quality flag.
    Timezone-less timestamps are REJECTED, not guessed.
  * Out-of-range values are FLAGGED (marked not observed and counted), never clipped.
  * The median step must match the declared cadence. Gaps and duplicates are counted and reported.
  * Nothing is interpolated: a gap simply ends the contiguous run that a fit may use.
  * Every channel carries a boolean ``observed`` mask next to its value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

import numpy as np

from src.physics.params import MODES

INPUT_CHANNELS: tuple[str, ...] = ("utilisation", "outside_temp_c", "humidity_pct", "chw_requested_c")
OUTPUT_CHANNELS: tuple[str, ...] = ("it_power_kw", "t_in_c", "t_out_c", "cooling_power_kw")
MODE_CHANNEL = "cooling_mode"
ALL_CHANNELS: tuple[str, ...] = INPUT_CHANNELS + OUTPUT_CHANNELS + (MODE_CHANNEL,)

# channel -> (expected unit, lowest plausible, highest plausible). Out of range => flagged, never clipped.
PLAUSIBLE: dict[str, tuple[str, float, float]] = {
    "utilisation": ("fraction", 0.0, 1.0),
    "outside_temp_c": ("degC", -40.0, 55.0),
    "humidity_pct": ("percent", 0.0, 100.0),
    "chw_requested_c": ("degC", 3.0, 25.0),
    "it_power_kw": ("kW", 0.0, 1.0e5),
    "t_in_c": ("degC", 5.0, 45.0),
    "t_out_c": ("degC", 5.0, 70.0),
    "cooling_power_kw": ("kW", 0.0, 1.0e5),
}
GOOD_QUALITY = frozenset({"ok", "good", "0", ""})


class CalibrationDataError(ValueError):
    """The dataset breaks the import schema (timezone-less time, unknown channel or unit, cadence mismatch...)."""


@dataclass
class CalibrationData:
    dataset_id: str
    ts: np.ndarray  # datetime64[s], UTC, strictly regular grid
    cadence_s: float
    values: dict[str, np.ndarray]  # channel -> float array (nan where not observed)
    observed: dict[str, np.ndarray]  # channel -> bool array
    mode: np.ndarray  # object array of mode strings ("" where not observed)
    synthetic: bool = False
    report: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        n = len(self.ts)
        for ch in INPUT_CHANNELS + OUTPUT_CHANNELS:
            if ch not in self.values or ch not in self.observed:
                raise CalibrationDataError(f"channel {ch!r} missing")
            if len(self.values[ch]) != n or len(self.observed[ch]) != n:
                raise CalibrationDataError(f"channel {ch!r} has the wrong length")
        if len(self.mode) != n:
            raise CalibrationDataError("mode has the wrong length")
        if not 0 < self.cadence_s <= 3600:
            raise CalibrationDataError("cadence_s must be in (0, 3600]")

    @property
    def n_rows(self) -> int:
        return len(self.ts)

    @property
    def n_days(self) -> float:
        return self.n_rows * self.cadence_s / 86400.0


def _parse_ts(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        dt = raw
    else:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError as exc:
            raise CalibrationDataError(f"unparseable timestamp {raw!r}") from exc
    if dt.tzinfo is None:
        raise CalibrationDataError(f"timestamp {raw!r} has no timezone; refusing to guess")
    return dt.astimezone(timezone.utc)


def from_tidy_rows(
    rows: Iterable[Mapping[str, Any]], *, dataset_id: str, cadence_s: float, synthetic: bool = False
) -> CalibrationData:
    """Build a regular-grid CalibrationData from tidy rows ``{ts, channel, value, unit, quality}``."""
    cells: dict[tuple[int, str], tuple[Any, bool]] = {}
    duplicates = 0
    unknown_quality = 0
    flagged: dict[str, int] = {}
    stamps: set[int] = set()
    for row in rows:
        ch = row.get("channel")
        if ch not in ALL_CHANNELS:
            raise CalibrationDataError(f"unknown channel {ch!r}; allowed: {ALL_CHANNELS}")
        t = int(_parse_ts(row["ts"]).timestamp())
        stamps.add(t)
        if ch != MODE_CHANNEL:
            unit = str(row.get("unit", ""))
            if unit != PLAUSIBLE[ch][0]:
                raise CalibrationDataError(f"channel {ch!r}: unit {unit!r}, expected {PLAUSIBLE[ch][0]!r}")
        ok = str(row.get("quality", "ok")).lower() in GOOD_QUALITY
        if not ok:
            unknown_quality += 1
        if (t, ch) in cells:
            duplicates += 1
            continue  # keep the first, count the rest
        cells[(t, ch)] = (row.get("value"), ok)
    if not stamps:
        raise CalibrationDataError("no rows")

    ordered = sorted(stamps)
    if len(ordered) > 1:
        median_step = float(np.median(np.diff(ordered)))
        if abs(median_step - cadence_s) > 1e-6:
            raise CalibrationDataError(f"median step {median_step} s does not match declared cadence {cadence_s} s")
    t0, t1 = ordered[0], ordered[-1]
    step = int(round(cadence_s))
    if step != cadence_s or any((t - t0) % step for t in ordered):
        raise CalibrationDataError("timestamps do not sit on the declared cadence grid")
    grid = np.arange(t0, t1 + step, step, dtype=np.int64)
    n = len(grid)
    index = {int(t): i for i, t in enumerate(grid)}

    values = {ch: np.full(n, np.nan) for ch in INPUT_CHANNELS + OUTPUT_CHANNELS}
    observed = {ch: np.zeros(n, dtype=bool) for ch in values}
    mode = np.array([""] * n, dtype=object)
    for ch in INPUT_CHANNELS + OUTPUT_CHANNELS:
        flagged[ch] = 0
    for (t, ch), (val, ok) in cells.items():
        i = index[t]
        if ch == MODE_CHANNEL:
            if ok and val in MODES:
                mode[i] = val
            continue
        _, lo, hi = PLAUSIBLE[ch]
        try:
            x = float(val)
        except (TypeError, ValueError):
            flagged[ch] += 1
            continue
        if not ok:
            continue
        if not math.isfinite(x) or not lo <= x <= hi:
            flagged[ch] += 1  # flagged, never clipped
            continue
        values[ch][i] = x
        observed[ch][i] = True

    report = {
        "rows_on_grid": n,
        "rows_with_data": len(ordered),
        "gaps": int(n - len(ordered)),
        "duplicates": duplicates,
        "bad_quality_cells": unknown_quality,
        "out_of_range_flagged": flagged,
        "observed_fraction": {ch: float(observed[ch].mean()) for ch in observed},
    }
    return CalibrationData(
        dataset_id=dataset_id,
        ts=grid.astype("datetime64[s]"),
        cadence_s=float(cadence_s),
        values=values,
        observed=observed,
        mode=mode,
        synthetic=synthetic,
        report=report,
    )
