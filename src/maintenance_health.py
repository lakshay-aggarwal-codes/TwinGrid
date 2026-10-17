"""Asset health indicator from stored telemetry (Task 28). Pure: no database, no clock, no randomness (timestamps are formatted, never read).

WHAT THIS IS. A transparent RULE on simulated data: per sensor, the share of invalid samples, whether the latest valid
value is outside the sensor's valid range, and a straight-line TREND (ordinary least squares) over the window, expressed
as the share of the valid range it moved. The status is the worst of those rules. It is a data-health and drift
indicator, NOT a failure prediction.

WHAT THIS IS NOT. There is no remaining-life estimate: the repo's predictive-maintenance model was trained on NASA
C-MAPSS (aircraft-engine proxy data) and has no valid mapping to this facility's telemetry, and no rule here extrapolates
a failure time. ``REMAINING_LIFE`` says so and the UI shows the trend only. An asset with no sensor, and a sensor with
too few samples, is ``no_data`` (NOT MEASURED), never "ok".
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

LABEL = "rule-based indicator on simulated data; not a failure prediction"
REMAINING_LIFE: Mapping[str, Any] = {
    "available": False,
    "reason": (
        "No validated remaining-life model applies to this facility. The predictive-maintenance model was trained on "
        "NASA C-MAPSS (aircraft-engine proxy data) and has no valid mapping to this telemetry. Trend only."
    ),
}

OK, WATCH, WARNING, NO_DATA = "ok", "watch", "warning", "no_data"
SEVERITY: Mapping[str, int] = {NO_DATA: 0, OK: 1, WATCH: 2, WARNING: 3}

MIN_SAMPLES = 12  # valid samples needed before a trend or a status is given
INVALID_WATCH, INVALID_WARNING = 0.05, 0.20  # share of the window's samples that are flagged invalid
DRIFT_WATCH_PCT, DRIFT_WARNING_PCT = 10.0, 25.0  # |change over the window| as % of (max_valid - min_valid)
MAX_SERIES_POINTS = 48
HOURS_DEFAULT, HOURS_MIN, HOURS_MAX = 24, 1, 168

Sample = tuple[float, float, bool]  # (epoch seconds, value, quality == "ok")


def _iso(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=timezone.utc).isoformat()


def _ols_slope(points: Sequence[tuple[float, float]]) -> float | None:
    """Slope of value against time (value per second); None for fewer than two points or no time spread."""
    n = len(points)
    if n < 2:
        return None
    mt = sum(t for t, _ in points) / n
    mv = sum(v for _, v in points) / n
    den = sum((t - mt) ** 2 for t, _ in points)
    if den == 0:
        return None
    return sum((t - mt) * (v - mv) for t, v in points) / den


def _series(points: Sequence[tuple[float, float]], max_points: int = MAX_SERIES_POINTS) -> list[dict[str, Any]]:
    """Mean per equal-width time bucket (at most ``max_points``), oldest first; empty buckets are omitted."""
    if not points:
        return []
    t0, t1 = points[0][0], points[-1][0]
    if t1 == t0:
        return [{"t": _iso(t0), "v": sum(v for _, v in points) / len(points)}]
    width = (t1 - t0) / max_points
    buckets: dict[int, list[tuple[float, float]]] = {}
    for t, v in points:
        buckets.setdefault(min(max_points - 1, int((t - t0) / width)), []).append((t, v))
    out = []
    for i in sorted(buckets):
        b = buckets[i]
        out.append({"t": _iso(sum(t for t, _ in b) / len(b)), "v": sum(v for _, v in b) / len(b)})
    return out


def summarize_sensor(
    samples: Sequence[Sample], min_valid: float | None, max_valid: float | None, *, unit: str = ""
) -> dict[str, Any]:
    """Health of one sensor from its window of samples, oldest first. See the module docstring for the rules."""
    ordered = sorted(samples, key=lambda s: s[0])
    ok = [(t, v) for t, v, good in ordered if good and math.isfinite(v)]
    total = len(ordered)
    invalid = total - len(ok)
    invalid_share = invalid / total if total else 0.0
    base: dict[str, Any] = {
        "samples": total,
        "valid_samples": len(ok),
        "invalid_share": invalid_share,
        "unit": unit,
        "min_valid": min_valid,
        "max_valid": max_valid,
    }
    if len(ok) < MIN_SAMPLES:
        return {
            **base,
            "status": NO_DATA,
            "reasons": [f"fewer than {MIN_SAMPLES} valid samples in the window: NOT MEASURED"],
            "latest": None,
            "trend": None,
            "series": [],
        }

    latest_t, latest_v = ok[-1]
    reasons: list[str] = []
    level = OK

    def raise_to(new: str, why: str) -> None:
        nonlocal level
        reasons.append(why)
        if SEVERITY[new] > SEVERITY[level]:
            level = new

    if invalid_share >= INVALID_WARNING:
        raise_to(WARNING, f"{invalid_share:.0%} of samples are flagged invalid")
    elif invalid_share >= INVALID_WATCH:
        raise_to(WATCH, f"{invalid_share:.0%} of samples are flagged invalid")

    out_of_range = (min_valid is not None and latest_v < min_valid) or (max_valid is not None and latest_v > max_valid)
    if out_of_range:
        raise_to(WARNING, "the latest valid value is outside the sensor's valid range")

    slope = _ols_slope(ok)
    span_s = ok[-1][0] - ok[0][0]
    trend: dict[str, Any] | None = None
    if slope is not None and span_s > 0:
        change = slope * span_s  # fitted change over the observed span
        rng = None if min_valid is None or max_valid is None or max_valid <= min_valid else max_valid - min_valid
        drift_pct = abs(change) / rng * 100.0 if rng else None
        direction = "flat" if drift_pct is not None and drift_pct < 1.0 else ("up" if change > 0 else "down")
        if change == 0:
            direction = "flat"
        trend = {
            "slope_per_day": slope * 86400.0,
            "change_over_window": change,
            "span_hours": span_s / 3600.0,
            "drift_pct_of_range": drift_pct,
            "direction": direction,
        }
        if drift_pct is not None:
            if drift_pct >= DRIFT_WARNING_PCT:
                raise_to(WARNING, f"fitted trend moved {drift_pct:.0f}% of the valid range over the window")
            elif drift_pct >= DRIFT_WATCH_PCT:
                raise_to(WATCH, f"fitted trend moved {drift_pct:.0f}% of the valid range over the window")

    return {
        **base,
        "status": level,
        "reasons": reasons,
        "latest": {"t": _iso(latest_t), "value": latest_v},
        "trend": trend,
        "series": _series(ok),
    }


def asset_status(sensor_summaries: Sequence[Mapping[str, Any]]) -> str:
    """Worst status among sensors that have data; ``no_data`` only when no sensor has any."""
    known = [s["status"] for s in sensor_summaries if s["status"] != NO_DATA]
    if not known:
        return NO_DATA
    return max(known, key=lambda s: SEVERITY[s])


def build_assets(
    assets: Sequence[Mapping[str, Any]], sensors_by_asset: Mapping[int, Sequence[Mapping[str, Any]]]
) -> list[dict[str, Any]]:
    """One row per asset. ``sensors_by_asset[asset_id]`` holds ``{measurand, external_id, summary}`` items."""
    rows: list[dict[str, Any]] = []
    for a in assets:
        sensors = list(sensors_by_asset.get(a["id"], ()))
        status = asset_status([s["summary"] for s in sensors]) if sensors else NO_DATA
        rows.append(
            {
                "asset_id": a["id"],
                "external_id": a["external_id"],
                "name": a["name"],
                "asset_type": a["asset_type"],
                "status": status,
                "sensor_count": len(sensors),
                "note": None if sensors else "No sensor is attached to this asset: health is NOT MEASURED.",
                "sensors": [
                    {"measurand": s["measurand"], "external_id": s["external_id"], **s["summary"]} for s in sensors
                ],
                "remaining_life": dict(REMAINING_LIFE),
            }
        )
    return rows


def counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    out = {OK: 0, WATCH: 0, WARNING: 0, NO_DATA: 0}
    for r in rows:
        out[r["status"]] += 1
    return out
