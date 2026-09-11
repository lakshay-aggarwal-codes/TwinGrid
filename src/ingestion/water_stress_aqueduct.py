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

import logging
from pathlib import Path
from typing import List, Optional

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

    raise FileNotFoundError(
        f"Aqueduct 4.0 baseline annual CSV not found under {real_data_dir}"
    )


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
    validate_required_columns(
        df, SELECTED_COLUMNS, source_name="Aqueduct 4.0 Water Stress"
    )

    clean_df = df[SELECTED_COLUMNS].copy()

    # Normalize text fields
    text_cols = ["string_id", "gid_1", "gid_0", "name_0", "name_1"]
    for col in text_cols:
        clean_df[col] = clean_df[col].apply(
            lambda x: str(x).strip() if pd.notna(x) and str(x).strip() != "nan" else ""
        )

    # Label columns (strip whitespace, fill empty)
    label_cols = [c for c in clean_df.columns if c.endswith("_label")]
    for col in label_cols:
        clean_df[col] = clean_df[col].apply(
            lambda x: str(x).strip() if pd.notna(x) else "No Data"
        )

    # Numeric score and raw columns: replace sentinel -9999.0 with NaN
    numeric_cols = [
        c
        for c in clean_df.columns
        if any(c.endswith(s) for s in ["_raw", "_score", "_cat", "_id", "_km2"])
        and c != "string_id"
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
        validate_numeric_range(
            clean_df, score_col, min_value=0.0, max_value=5.0, source_name="Aqueduct"
        )

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

    countries_count = (
        sorted_df[sorted_df["name_0"] != ""]["name_0"].nunique()
    )
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
