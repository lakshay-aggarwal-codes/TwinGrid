"""
Real grid carbon-intensity signal for the PPO reward's gamma (carbon) term.

Loads data/cleaned/carbon_intensity.csv (Phase 2's Electricity Maps
ingestion output) and builds a 24-value diurnal average (one value per
hour-of-day, averaged across all dates/zones present). This is real data,
but it's a diurnal AVERAGE, not a raw time series -- the RL environment
runs on an abstract recurring "hour", not calendar dates, so there is no
valid way to attach a specific date's intensity value to a training step.

Falls back to a flat, clearly-labeled default if the cleaned file isn't
present, so training remains runnable before Phase 2's ingestion has been
run -- never silently substitutes a fake-but-varying curve for a missing
real one.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
CLEANED_CARBON_PATH = REPO_ROOT / "data" / "cleaned" / "carbon_intensity.csv"

# World-average grid carbon intensity (gCO2eq/kWh), commonly cited (IEA/Ember).
# Used ONLY as an explicit, documented fallback constant -- never presented
# as real or site-specific data.
FALLBACK_FLAT_INTENSITY_GCO2_PER_KWH = 475.0


def load_diurnal_carbon_intensity(zone: str | None = None) -> tuple[np.ndarray, bool]:
    """
    Returns (intensity_by_hour, is_real) where intensity_by_hour is a
    length-24 array (index = hour of day, 0-23) of gCO2eq/kWh, and is_real
    indicates whether this came from real Electricity Maps data (True) or
    the flat fallback constant (False) -- callers should surface this
    distinction, not hide it.
    """
    if not CLEANED_CARBON_PATH.exists():
        logger.warning(
            "%s not found -- run `python scripts/run_ingestion.py --only carbon_electricity_maps` "
            "to use real carbon-intensity data. Using flat fallback of %.0f gCO2/kWh.",
            CLEANED_CARBON_PATH, FALLBACK_FLAT_INTENSITY_GCO2_PER_KWH,
        )
        return np.full(24, FALLBACK_FLAT_INTENSITY_GCO2_PER_KWH), False

    df = pd.read_csv(CLEANED_CARBON_PATH, parse_dates=["timestamp_utc"])
    if zone is not None:
        df = df[df["zone"] == zone]
        if df.empty:
            available = sorted(pd.read_csv(CLEANED_CARBON_PATH)["zone"].unique())
            logger.warning("Zone '%s' not found (available: %s). Using all zones instead.", zone, available)
            df = pd.read_csv(CLEANED_CARBON_PATH, parse_dates=["timestamp_utc"])

    df["hour"] = df["timestamp_utc"].dt.hour
    hourly_avg = df.groupby("hour")["carbon_intensity_gco2_per_kwh"].mean()

    intensity = np.full(24, FALLBACK_FLAT_INTENSITY_GCO2_PER_KWH)
    missing_hours = []
    for hour in range(24):
        if hour in hourly_avg.index:
            intensity[hour] = hourly_avg.loc[hour]
        else:
            missing_hours.append(hour)
    if missing_hours:
        logger.warning(
            "No real data for hours %s -- using flat fallback for those hours only.", missing_hours
        )

    logger.info(
        "Loaded real diurnal carbon intensity: min=%.0f max=%.0f mean=%.0f gCO2/kWh",
        intensity.min(), intensity.max(), intensity.mean(),
    )
    return intensity, True