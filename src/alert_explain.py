"""Task 18: deterministic "why did this alert fire" numbers, from the stored reading and the detector's own scaler.

PURE (no I/O, no model, no TensorFlow). What this is, exactly:

* ``feature_deviations`` places each of the detector's five input signals inside the range the detector's scaler saw
  in training (``data_min_`` .. ``data_max_``). ``centre_distance`` is ``|2 * position - 1|``: 0 at the middle of the
  training range, 1 at its edge, above 1 outside it. It is a deterministic residual of the INPUTS, computed from the
  same five values the detector reads. It is NOT the autoencoder's reconstruction error: that needs the whole 12-step
  window, which is not stored with an alert. While an anomaly episode is live, the detector's own per-feature
  reconstruction-error shares are in the live frame (``anomaly_status.explanation``; ``src/anomaly_explain.py``).
* ``score_vs_threshold`` compares the stored score with the detector's alert threshold and applies the existing
  severity rule (CRITICAL above 2 x threshold, ``api.services.anomaly_service.alert_severity``).
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

METHOD = "range-deviation"
METHOD_TEXT = (
    "Each signal is placed inside the range the detector saw in training. This is a deterministic deviation of the "
    "stored reading, not the detector's reconstruction error (which needs the whole 12-step window, not stored with an alert)."
)
#: Mirrors ``alert_severity`` in api/services/anomaly_service.py (a test pins the two together).
CRITICAL_FACTOR = 2.0


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def feature_deviations(
    values: Mapping[str, float], columns: Sequence[str], data_min: Sequence[float], data_max: Sequence[float]
) -> list[dict[str, Any]]:
    """One row per detector input, largest ``centre_distance`` first (ties: column order). Raises ValueError on bad input."""
    if not (len(columns) == len(data_min) == len(data_max)) or not columns:
        raise ValueError("scaler columns, minima and maxima must have the same non-zero length")
    rows: list[dict[str, Any]] = []
    for i, col in enumerate(columns):
        v, lo, hi = values.get(col), data_min[i], data_max[i]
        if not (_finite(v) and _finite(lo) and _finite(hi)) or hi <= lo:
            raise ValueError(f"cannot place {col!r}: value or training range is missing or invalid")
        position = (float(v) - lo) / (hi - lo)
        outside = max(0.0, -position, position - 1.0)
        rows.append(
            {
                "feature": col,
                "value": float(v),
                "train_min": float(lo),
                "train_max": float(hi),
                "position": position,
                "centre_distance": abs(2.0 * position - 1.0),
                "outside_range_by": outside,
                "outside_range": outside > 0.0,
                "_order": i,
            }
        )
    rows.sort(key=lambda r: (-r["centre_distance"], r["_order"]))
    for rank, r in enumerate(rows, start=1):
        r["rank"] = rank
        del r["_order"]
    return rows


def score_vs_threshold(score: float, threshold: float) -> dict[str, Any]:
    """``ratio`` = score / threshold; ``over_threshold`` mirrors the detector's alert rule (score above threshold)."""
    if not (_finite(score) and _finite(threshold)) or threshold <= 0:
        raise ValueError("score and a positive threshold are required")
    return {
        "score": float(score),
        "threshold": float(threshold),
        "ratio": float(score) / float(threshold),
        "margin": float(score) - float(threshold),
        "over_threshold": float(score) > float(threshold),
        "critical_above": CRITICAL_FACTOR * float(threshold),
        "severity_by_rule": "CRITICAL" if float(score) > CRITICAL_FACTOR * float(threshold) else "WARNING",
    }
