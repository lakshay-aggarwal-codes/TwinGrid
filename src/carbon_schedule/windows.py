"""Task 27: the best window to run a flexible load, from the 24-point carbon curve. Pure: no I/O, no FastAPI.

Honesty rules this module enforces (they are the point of the task):

* The curve is the **hour-of-day mean by site-local hour** (see ``src.carbon_provider``). It is not a forecast and not
  data for any specific date, so a suggestion is "which hours are usually lower", never "tomorrow at 13:00".
* A suggestion and a saving are produced only when the curve actually varies AND it is not an assumption. The flat
  fallback constant (and any flat series) yields "No carbon variation in current data" and no number. A curve that is
  partly or wholly an assumption (``is_fallback``) yields no window and no saving either.
* The only exception is the explicit synthetic demonstration profile, which is labelled as synthetic everywhere and is
  never mixed with data.
* Average intensity is not marginal intensity; the response says so when the series is an average.

Granularity is whole hours: a window of ``duration_h`` hours is the mean of that many consecutive hourly values.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from src.carbon_provider import CarbonSignal

MAX_DURATION_H = 24
MAX_LOAD_KW = 100_000.0
FLAT_TOLERANCE = 1e-9  # gCO2/kWh: a spread this small is "flat"

# Statuses
OK, NO_VARIATION, UNVERIFIED, SYNTHETIC_DEMO = "ok", "no_variation", "unverified", "synthetic_demo"
PROFILE_DATA, PROFILE_SYNTHETIC = "data", "synthetic_demo"

NO_VARIATION_HEADLINE = "No carbon variation in current data"
UNVERIFIED_HEADLINE = "Carbon data is incomplete or unverified"
SYNTHETIC_LABEL = "SYNTHETIC DEMONSTRATION profile, not grid data"

LABEL = "scheduling suggestion from an hour-of-day carbon profile, not a forecast"
BASIS = (
    "Each candidate window is the mean of the hour-of-day carbon intensity (site-local hours, whole hours) over its "
    "duration; emissions = load kW x duration h x that mean. The curve is an hour-of-day mean, not a forecast and not "
    "data for a specific date. The load is hypothetical (the value you entered). The baseline is the average of all "
    "allowed windows, or your reference start hour if you gave one."
)
AVERAGE_NOT_MARGINAL = "Average intensity is not marginal intensity: the real-world effect of moving load may differ."

# A deliberately artificial curve: mean 475 gCO2/kWh, 120 swing, lowest at 13:00, highest at 01:00 (site-local).
# Chosen only so the demonstration shows a visible window; it describes no real grid.
SYNTHETIC_CURVE: tuple[float, ...] = tuple(475.0 - 120.0 * math.cos(2 * math.pi * (h - 13) / 24) for h in range(24))


class ScheduleError(ValueError):
    """Invalid request parameters (the API maps this to a 422)."""


def is_flat(curve: Any) -> bool:
    arr = np.asarray(curve, dtype=float)
    return bool(np.ptp(arr) <= FLAT_TOLERANCE)


def validate(
    duration_h: int, load_kw: float, window_start: int, window_hours: int, reference_start_hour: int | None
) -> None:
    def whole(v: Any) -> bool:
        return isinstance(v, int) and not isinstance(v, bool)

    if not whole(duration_h) or not 1 <= duration_h <= MAX_DURATION_H:
        raise ScheduleError(f"duration_h must be a whole number of hours in [1, {MAX_DURATION_H}]")
    if not (isinstance(load_kw, (int, float)) and math.isfinite(load_kw) and 0 < load_kw <= MAX_LOAD_KW):
        raise ScheduleError(f"load_kw must be in (0, {MAX_LOAD_KW:g}]")
    if not whole(window_start) or not 0 <= window_start <= 23:
        raise ScheduleError("window_start must be a whole hour in [0, 23]")
    if not whole(window_hours) or not 1 <= window_hours <= 24:
        raise ScheduleError("window_hours must be a whole number of hours in [1, 24]")
    if window_hours < duration_h:
        raise ScheduleError("the allowed window is shorter than the load's duration")
    if reference_start_hour is not None:
        if not whole(reference_start_hour) or not 0 <= reference_start_hour <= 23:
            raise ScheduleError("reference_start_hour must be a whole hour in [0, 23]")
        if reference_start_hour not in candidate_starts(duration_h, window_start, window_hours):
            raise ScheduleError("reference_start_hour is not a start time that fits the allowed window")


def candidate_starts(duration_h: int, window_start: int, window_hours: int) -> list[int]:
    """Start hours (site-local, 0-23) whose whole run fits inside the allowed span. A 24 h span means "any time", so
    windows may wrap past midnight; a shorter span is a fixed interval and a run must finish inside it."""
    count = 24 if window_hours == 24 else window_hours - duration_h + 1
    return [(window_start + i) % 24 for i in range(count)]


def window_mean(curve: Any, start: int, duration_h: int) -> float:
    arr = np.asarray(curve, dtype=float)
    return float(np.mean([arr[(start + i) % 24] for i in range(duration_h)]))


def _window(curve: Any, start: int, duration_h: int, load_kw: float) -> dict[str, Any]:
    mean = window_mean(curve, start, duration_h)
    return {
        "start_hour": start,
        "end_hour": (start + duration_h) % 24,
        "mean_gco2_per_kwh": mean,
        "emissions_kg": load_kw * duration_h * mean / 1000.0,
    }


def plan(
    curve: Any,
    *,
    duration_h: int,
    load_kw: float,
    window_start: int = 0,
    window_hours: int = 24,
    reference_start_hour: int | None = None,
) -> dict[str, Any]:
    """Best, worst and baseline windows on a 24-point curve, and the saving. Deterministic: ties go to the earliest
    candidate in the allowed span. Callers decide whether the curve is fit to claim anything (see ``suggest``)."""
    validate(duration_h, load_kw, window_start, window_hours, reference_start_hour)
    arr = np.asarray(curve, dtype=float)
    if arr.shape != (24,) or not np.all(np.isfinite(arr)):
        raise ScheduleError("curve must be 24 finite values")
    starts = candidate_starts(duration_h, window_start, window_hours)
    windows = [_window(arr, s, duration_h, load_kw) for s in starts]
    best = min(windows, key=lambda w: w["mean_gco2_per_kwh"])  # min() keeps the first of equals
    worst = max(windows, key=lambda w: w["mean_gco2_per_kwh"])
    if reference_start_hour is None:
        avg_mean = float(np.mean([w["mean_gco2_per_kwh"] for w in windows]))
        baseline = {
            "kind": "average_of_allowed_windows",
            "start_hour": None,
            "end_hour": None,
            "mean_gco2_per_kwh": avg_mean,
            "emissions_kg": load_kw * duration_h * avg_mean / 1000.0,
        }
    else:
        baseline = {"kind": "reference_start", **_window(arr, reference_start_hour, duration_h, load_kw)}
    saved = baseline["emissions_kg"] - best["emissions_kg"]
    return {
        "candidates": len(windows),
        "best": best,
        "worst": worst,
        "baseline": baseline,
        "savings": {
            "emissions_kg": saved,
            "pct": 100.0 * saved / baseline["emissions_kg"] if baseline["emissions_kg"] > 0 else None,
        },
    }


def _hhmm(hour: int) -> str:
    return f"{hour:02d}:00"


def suggest(
    signal: CarbonSignal,
    *,
    profile: str = PROFILE_DATA,
    duration_h: int,
    load_kw: float,
    window_start: int = 0,
    window_hours: int = 24,
    reference_start_hour: int | None = None,
) -> dict[str, Any]:
    """The full response body. ``signal`` is the loaded carbon signal; ``profile="synthetic_demo"`` replaces its curve
    with the labelled synthetic one (the signal's own basis is still returned, so a screen can say what the data is)."""
    if profile not in (PROFILE_DATA, PROFILE_SYNTHETIC):
        raise ScheduleError("profile must be 'data' or 'synthetic_demo'")
    validate(duration_h, load_kw, window_start, window_hours, reference_start_hour)
    basis = signal.basis()
    params = {
        "duration_h": duration_h,
        "load_kw": load_kw,
        "window_start": window_start,
        "window_hours": window_hours,
        "reference_start_hour": reference_start_hour,
    }
    body: dict[str, Any] = {
        "label": LABEL,
        "basis": BASIS,
        "profile": profile,
        "inputs": params,
        "carbon": basis,
        "site_timezone": signal.site_timezone,
        "curve_gco2_per_kwh": None,
        "best": None,
        "worst": None,
        "baseline": None,
        "savings": None,
        "synthetic_label": None,
        "caveats": [],
    }
    plan_args = {k: v for k, v in params.items()}

    if profile == PROFILE_SYNTHETIC:
        result = plan(SYNTHETIC_CURVE, **plan_args)
        body.update(result)
        body["curve_gco2_per_kwh"] = list(SYNTHETIC_CURVE)
        body["status"] = SYNTHETIC_DEMO
        body["synthetic_label"] = SYNTHETIC_LABEL
        body["headline"] = _headline(result["best"], duration_h, prefix="Demonstration only: ")
        body["message"] = (
            f"{SYNTHETIC_LABEL}. The curve is made up to show how the suggestion works; the figures below are "
            "illustrative and say nothing about the real grid."
        )
        body["caveats"] = ["Synthetic profile: not grid data, not a forecast."]
        return body

    curve = signal.curve_by_site_local_hour
    if is_flat(curve):
        body["status"] = NO_VARIATION
        body["curve_gco2_per_kwh"] = [float(x) for x in curve]
        body["headline"] = NO_VARIATION_HEADLINE
        what = (
            "The carbon signal is the flat assumed constant, not grid data, so every hour looks the same"
            if signal.semantic == "constant_assumption"
            else "The carbon series has the same intensity in every hour"
        )
        body["message"] = f"{NO_VARIATION_HEADLINE}. {what}: no window is better than another and no saving is claimed."
        return body
    # Same standard as carbon_provider.format_carbon_reduction: no claim from an assumption or an undocumented series.
    if signal.is_fallback or signal.semantic in ("constant_assumption", "unknown"):
        body["status"] = UNVERIFIED
        body["headline"] = UNVERIFIED_HEADLINE
        reason = (
            "some hours of the day have no data and are filled by an assumption"
            if signal.missing_hours
            else "the series has no documented meaning (average or marginal) or its provenance is not established"
        )
        body["message"] = f"{UNVERIFIED_HEADLINE}: {reason}, so no window and no saving is suggested."
        return body

    result = plan(curve, **plan_args)
    body.update(result)
    body["status"] = OK
    body["curve_gco2_per_kwh"] = [float(x) for x in curve]
    body["headline"] = _headline(result["best"], duration_h)
    body["message"] = (
        f"Hours of the day with lower carbon intensity in the loaded series. {basis['statement']} "
        "This is a usual pattern, not a forecast for a particular day."
    )
    body["caveats"] = [AVERAGE_NOT_MARGINAL] if signal.semantic == "average" else []
    return body


def _headline(best: dict[str, Any], duration_h: int, prefix: str = "") -> str:
    return (
        f"{prefix}Lowest-carbon {duration_h}-hour window: {_hhmm(best['start_hour'])} to {_hhmm(best['end_hour'])} "
        "(site-local time)"
    )
