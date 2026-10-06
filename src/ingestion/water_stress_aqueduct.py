"""
WRI Aqueduct 4.0 Water-Stress Data Ingestion Module.

Extracts, validates, and normalizes baseline water-stress indicators from:
realData/aqueduct-4-0-water-risk-data/Aqueduct40_waterrisk_download_Y2023M07D05/CVS/Aqueduct40_baseline_annual_y2023m07d05.csv
into a clean, standardized dataset:
data/cleaned/water_stress_aqueduct.csv

Preserves essential geographic identifiers (ISO country code, admin level 1,
hydro-basin identifiers) and handles Aqueduct sentinel values (-9999.0 / 9999.0)
for seamless integration with Digital Twin cooling-mode arbitration.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

from .base import (
    deduplicate_records,
    get_ingestion_logger,
    get_real_data_dir,
    save_cleaned_dataset,
    validate_non_empty,
    validate_numeric_range,
    validate_required_columns,
)

logger = get_ingestion_logger("water_stress_aqueduct")

# Core geographic and water stress columns to retain and normalize
SELECTED_COLUMNS = [
    # Geographic Identifiers
    "string_id",
    "aq30_id",
    "pfaf_id",
    "gid_1",
    "aqid",
    "gid_0",
    "name_0",
    "name_1",
    "area_km2",
    # Baseline Water Stress (BWS: withdrawal / available supply)
    "bws_raw",
    "bws_score",
    "bws_cat",
    "bws_label",
    # Baseline Water Depletion (BWD: consumption / available supply)
    "bwd_raw",
    "bwd_score",
    "bwd_cat",
    "bwd_label",
    # Interannual Variability (IAV)
    "iav_raw",
    "iav_score",
    "iav_cat",
    "iav_label",
    # Seasonal Variability (SEV)
    "sev_raw",
    "sev_score",
    "sev_cat",
    "sev_label",
    # Riverine Flood Risk (RFR)
    "rfr_raw",
    "rfr_score",
    "rfr_cat",
    "rfr_label",
    # Drought Risk (DRR)
    "drr_raw",
    "drr_score",
    "drr_cat",
    "drr_label",
]

# WRI Aqueduct sentinel values that denote missing / uncalculated values
SENTINEL_VALUES = [-9999.0, 9999.0]


# ---------------------------------------------------------------------------
# T23 (roadmap §13.7): what the Aqueduct number is, and is not.
#
# It is WRI Aqueduct 4.0 (download Y2023M07D05) field ``bws_score``, an ANNUAL, COUNTRY-level index:
# the mean of the country's sub-national rows, then min-max scaled over the whole table. It is an index, not
# a physical quantity, and not availability, supply, consumption or a regulatory limit. The simulator's own
# time variation is a SYNTHETIC scenario; the drought shield is triggered by that scenario, never by this
# baseline. ``bws_raw == 9999`` means "arid / low water use" and is NOT read as high stress.
# ---------------------------------------------------------------------------
AQUEDUCT_DATASET = "WRI Aqueduct 4.0 baseline annual"
AQUEDUCT_RELEASE = "Y2023M07D05"
AQUEDUCT_FIELD = "bws_score"
AQUEDUCT_GEOGRAPHY = "country"
AQUEDUCT_AGGREGATION = "mean of the country's sub-national rows"
AQUEDUCT_NORMALISATION = "min-max over all non-sentinel rows of the table"
AQUEDUCT_TEMPORAL_ANNUAL = "annual"
AQUEDUCT_TEMPORAL_MONTHLY = "monthly_climatology"
AQUEDUCT_META_FILENAME = "water_stress_aqueduct.meta.json"
WATER_STRESS_KIND_SCENARIO = "scenario"


def baseline_meta(temporal: str = AQUEDUCT_TEMPORAL_ANNUAL, **extra: Any) -> dict[str, Any]:
    """The ``water_stress_baseline_meta`` block (JSON-safe). Never claims more than country-level, annual."""
    meta = {
        "dataset": AQUEDUCT_DATASET,
        "release": AQUEDUCT_RELEASE,
        "field": AQUEDUCT_FIELD,
        "geography": AQUEDUCT_GEOGRAPHY,
        "aggregation": AQUEDUCT_AGGREGATION,
        "normalisation": AQUEDUCT_NORMALISATION,
        "temporal": temporal,
        "meaning": "relative index (0-1 after scaling); not water availability, supply, consumption or a regulatory limit",
    }
    meta.update(extra)
    return meta


def sentinel_counts(df: pd.DataFrame) -> dict[str, int]:
    """Counts of Aqueduct sentinels in a RAW (or cleaned) table: -9999 (missing), +9999 (arid / low use)."""
    out: dict[str, int] = {"rows": int(len(df))}
    for col in ("bws_score", "bws_raw"):
        if col in df.columns:
            num = pd.to_numeric(df[col], errors="coerce")
            out[f"{col}_minus9999"] = int((num == -9999.0).sum())
            out[f"{col}_plus9999"] = int((num == 9999.0).sum())
            out[f"{col}_nan"] = int(num.isna().sum())
    return out


@dataclass(frozen=True)
class AqueductBaseline:
    """Country-level baseline context. ``value`` is None when it cannot be computed (reason in ``meta``)."""

    value: Optional[float]
    meta: dict[str, Any] = field(default_factory=dict)


def _normalised_country_value(df: pd.DataFrame, country: str, column: str) -> tuple[Optional[float], dict[str, int]]:
    num = pd.to_numeric(df[column], errors="coerce")
    num = num.where(~num.isin(SENTINEL_VALUES))  # sentinels -> NaN, excluded from every mean and from min/max
    counts = {
        "table_rows": int(len(df)),
        "sentinel_rows_excluded": int(pd.to_numeric(df[column], errors="coerce").isin(SENTINEL_VALUES).sum()),
        "nan_rows": int(num.isna().sum()),
    }
    valid = num.dropna()
    if valid.empty:
        return None, counts
    lo, hi = float(valid.min()), float(valid.max())
    rows = df["name_0"].astype(str).str.strip().str.lower() == country.strip().lower()
    counts["country_rows"] = int(rows.sum())
    raw = num[rows].dropna()
    counts["country_rows_used"] = int(len(raw))
    if raw.empty:
        return None, counts
    if hi <= lo:
        return 0.5, counts  # degenerate: constant table, cannot normalise
    return float((raw.mean() - lo) / (hi - lo)), counts


def country_baseline(df: pd.DataFrame, country: str, *, column: str = AQUEDUCT_FIELD) -> AqueductBaseline:
    """Annual country baseline from a cleaned/raw Aqueduct table. Sentinel rows are excluded from all means."""
    required = {"name_0", column}
    if not required.issubset(df.columns):
        return AqueductBaseline(
            None,
            baseline_meta(
                country=country, available=False, reason=f"missing columns {sorted(required - set(df.columns))}"
            ),
        )
    value, counts = _normalised_country_value(df, country, column)
    if value is None:
        return AqueductBaseline(
            None,
            baseline_meta(
                country=country, available=False, reason="country absent or all rows sentinel/NaN", counts=counts
            ),
        )
    return AqueductBaseline(value, baseline_meta(country=country, available=True, counts=counts))


def monthly_climatology(df: pd.DataFrame, country: str, month_map: Mapping[int, str]) -> dict[int, Optional[float]]:
    """Monthly climatological baseline: ``month_map`` {1..12: column name} is REQUIRED and must be explicit.

    Each month is normalised exactly like the annual value (own table min-max). The result is a "monthly
    climatological baseline" (typical month, not a forecast or a measurement of any specific year).
    """
    if sorted(month_map) != list(range(1, 13)):
        raise ValueError("month_map must name a column for each month 1..12 explicitly")
    missing = [c for c in month_map.values() if c not in df.columns]
    if missing:
        raise ValueError(f"month_map columns not in table: {missing}")
    return {m: _normalised_country_value(df, country, col)[0] for m, col in month_map.items()}


def load_country_baseline(
    country: str,
    *,
    path: Optional[Path] = None,
    temporal: Optional[str] = None,
    month_map: Optional[Mapping[int, str]] = None,
    month: Optional[int] = None,
) -> AqueductBaseline:
    """Baseline for ``country`` from the cleaned file. ``AQUEDUCT_TEMPORAL`` (env) selects ``annual`` (default)
    or ``monthly_climatology``; the latter needs an explicit ``month_map`` and ``month`` (no implicit mapping).
    """
    from .base import get_cleaned_data_dir  # local: keeps import cost off the module-level path

    temporal = (temporal or os.getenv("AQUEDUCT_TEMPORAL") or AQUEDUCT_TEMPORAL_ANNUAL).strip()
    if temporal not in (AQUEDUCT_TEMPORAL_ANNUAL, AQUEDUCT_TEMPORAL_MONTHLY):
        raise ValueError(f"AQUEDUCT_TEMPORAL must be 'annual' or 'monthly_climatology', got {temporal!r}")
    src = Path(path) if path is not None else get_cleaned_data_dir() / "water_stress_aqueduct.csv"
    if not src.exists():
        return AqueductBaseline(
            None, baseline_meta(temporal, country=country, available=False, reason=f"{src.name} not found")
        )
    df = pd.read_csv(src, low_memory=False)
    if temporal == AQUEDUCT_TEMPORAL_ANNUAL:
        return country_baseline(df, country)
    if month_map is None or month is None or not 1 <= int(month) <= 12:
        raise ValueError("monthly_climatology requires an explicit month_map and a month in 1..12")
    value = monthly_climatology(df, country, month_map)[int(month)]
    return AqueductBaseline(
        value,
        baseline_meta(
            AQUEDUCT_TEMPORAL_MONTHLY,
            country=country,
            available=value is not None,
            month=int(month),
            month_map={int(k): v for k, v in month_map.items()},
        ),
    )


def resolve_aqueduct_source(source_path: Optional[Path] = None) -> Path:
    """
    Locate the baseline annual Aqueduct CSV file.

    Args:
        source_path: Explicit file path or None to search.

    Returns:
        Resolved Path.
    """
    if source_path is not None and source_path.exists():
        return source_path

    real_data_dir = get_real_data_dir()
    # Expected relative path
    candidate = (
        real_data_dir
        / "aqueduct-4-0-water-risk-data"
        / "Aqueduct40_waterrisk_download_Y2023M07D05"
        / "CVS"
        / "Aqueduct40_baseline_annual_y2023m07d05.csv"
    )
    if candidate.exists():
        return candidate

    # Search for any baseline annual CSV file
    matches = list(real_data_dir.glob("**/Aqueduct40_baseline_annual_*.csv"))
    if matches:
        return matches[0]

    raise FileNotFoundError(f"Aqueduct 4.0 baseline annual CSV not found under {real_data_dir}")


def normalize_aqueduct_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean and normalize the Aqueduct water risk table.

    - Validates required columns.
    - Preserves all crucial geographic identifiers (country, state, basin).
    - Normalizes sentinel values (-9999.0, 9999.0) in continuous raw metrics to NaN
      while retaining descriptive categorical labels (e.g., 'Arid and Low Water Use').
    - Cleans string whitespace.
    - Adds provenance tag.

    Args:
        df: Raw DataFrame.

    Returns:
        Cleaned, normalized DataFrame.
    """
    validate_required_columns(df, SELECTED_COLUMNS, source_name="Aqueduct 4.0 Water Stress")

    clean_df = df[SELECTED_COLUMNS].copy()

    # Normalize text fields
    text_cols = ["string_id", "gid_1", "gid_0", "name_0", "name_1"]
    for col in text_cols:
        clean_df[col] = clean_df[col].apply(lambda x: str(x).strip() if pd.notna(x) and str(x).strip() != "nan" else "")

    # Label columns (strip whitespace, fill empty)
    label_cols = [c for c in clean_df.columns if c.endswith("_label")]
    for col in label_cols:
        clean_df[col] = clean_df[col].apply(lambda x: str(x).strip() if pd.notna(x) else "No Data")

    # Numeric score and raw columns: replace sentinel -9999.0 with NaN
    numeric_cols = [
        c
        for c in clean_df.columns
        if any(c.endswith(s) for s in ["_raw", "_score", "_cat", "_id", "_km2"]) and c != "string_id"
    ]
    for col in numeric_cols:
        clean_df[col] = pd.to_numeric(clean_df[col], errors="coerce")
        # For scores and categories, -9999 represents missing/unrated data
        if col.endswith("_score") or col.endswith("_cat"):
            clean_df.loc[clean_df[col].isin(SENTINEL_VALUES), col] = np.nan
        # For raw metrics, -9999 is missing, but note: 9999 in bws_raw represents arid/low water use
        if col.endswith("_raw"):
            clean_df.loc[clean_df[col] == -9999.0, col] = np.nan

    # Validate score range (should be between 0.0 and 5.0 where present)
    for score_col in ["bws_score", "bwd_score", "iav_score", "sev_score"]:
        validate_numeric_range(clean_df, score_col, min_value=0.0, max_value=5.0, source_name="Aqueduct")

    # Add source provenance column
    clean_df["data_source"] = "wri_aqueduct_4.0"

    return clean_df


def ingest_aqueduct(
    source_file: Optional[Path] = None,
    output_filename: str = "water_stress_aqueduct.csv",
    overwrite: bool = True,
) -> Path:
    """
    Execute Aqueduct water-stress data ingestion pipeline.

    1. Resolves raw baseline annual CSV.
    2. Reads and filters selected indicators.
    3. Normalizes types, sentinels, labels, and geographic identifiers.
    4. Deduplicates by 'string_id'.
    5. Deterministically sorts by 'string_id'.
    6. Saves to data/cleaned/water_stress_aqueduct.csv.

    Args:
        source_file: Path to source CSV.
        output_filename: Output CSV filename.
        overwrite: Overwrite flag.

    Returns:
        Path to generated cleaned CSV.
    """
    logger.info("Starting WRI Aqueduct 4.0 Water-Stress data ingestion...")
    csv_path = resolve_aqueduct_source(source_file)
    logger.info(f"Reading Aqueduct baseline data from {csv_path.name}")

    # Read selected columns to optimize memory usage (file is ~200MB)
    df_raw = pd.read_csv(csv_path, usecols=SELECTED_COLUMNS, low_memory=False)
    validate_non_empty(df_raw, source_name="Aqueduct Water Stress")

    df_clean = normalize_aqueduct_dataframe(df_raw)

    # Deduplicate by primary key (string_id)
    deduped = deduplicate_records(
        df_clean,
        subset=["string_id"],
        source_name="Aqueduct Water Stress",
        logger=logger,
    )

    # Sort deterministically
    sorted_df = deduped.sort_values(by=["string_id"]).reset_index(drop=True)

    output_path = save_cleaned_dataset(
        sorted_df,
        filename=output_filename,
        overwrite=overwrite,
        logger=logger,
    )

    # T23: record sentinel counts of the RAW table next to the cleaned file (the cleaned file has them as NaN).
    counts = sentinel_counts(df_raw)
    Path(output_path).with_name(AQUEDUCT_META_FILENAME).write_text(
        json.dumps(baseline_meta(sentinel_counts=counts), indent=2, sort_keys=True), encoding="utf-8"
    )
    logger.info(f"Aqueduct sentinel counts (raw): {counts}")

    countries_count = sorted_df[sorted_df["name_0"] != ""]["name_0"].nunique()
    logger.info(
        f"Aqueduct ingestion complete: {len(df_raw):,} raw rows -> "
        f"{len(sorted_df):,} cleaned rows covering {countries_count} countries."
    )
    return output_path


def main() -> None:
    """Module entry point called by the ingestion runner."""
    ingest_aqueduct()


if __name__ == "__main__":
    main()
