"""
Electricity Maps Carbon & Grid Coverage Ingestion Module.

Normalizes the Electricity Maps coverage dataset from:
realData/2026-09-06-electricity-maps-coverage-data.csv
into a clean, standardized dataset:
data/cleaned/carbon_electricity_maps.csv
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from .base import (
    deduplicate_records,
    get_ingestion_logger,
    get_real_data_dir,
    save_cleaned_dataset,
    validate_non_empty,
    validate_required_columns,
)

logger = get_ingestion_logger("carbon_electricity_maps")

# Expected raw columns in the Electricity Maps dataset
EXPECTED_RAW_COLUMNS = [
    "zone",
    "zone_key",
    "tier",
    "signal",
    "available_from",
    "historical_temporal_granularity",
    "real_time_granularity",
    "forecast_source",
    "horizons",
    "forecast_granularity",
]

# Output column names
NORMALIZED_COLUMNS = [
    "zone",
    "zone_key",
    "tier",
    "signal",
    "available_from_utc",
    "historical_temporal_granularity",
    "real_time_granularity",
    "forecast_source",
    "horizons",
    "forecast_granularity",
    "data_source",
]


def resolve_electricity_maps_source(source_path: Optional[Path] = None) -> Path:
    """
    Find the Electricity Maps coverage data file.

    Args:
        source_path: Explicit path or None to search realData/.

    Returns:
        Path to existing file.
    """
    if source_path is not None and source_path.exists():
        return source_path

    real_data_dir = get_real_data_dir()
    # Direct candidate matching the known provenance slug
    exact_file = real_data_dir / "2026-09-06-electricity-maps-coverage-data.csv"
    if exact_file.exists():
        return exact_file

    # Pattern search
    candidates = list(real_data_dir.glob("*electricity-maps*.csv"))
    if candidates:
        return sorted(candidates)[0]

    raise FileNotFoundError(
        f"Could not find Electricity Maps CSV file in {real_data_dir}"
    )


def normalize_electricity_maps_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean and normalize the Electricity Maps DataFrame.

    - Validates presence of required columns.
    - Normalizes column names.
    - Parses available_from into UTC ISO-8601 timestamps.
    - Cleans string whitespace and handles missing zone_key / tier gracefully.
    - Adds data_source provenance column.

    Args:
        df: Raw DataFrame.

    Returns:
        Cleaned, normalized DataFrame.
    """
    validate_required_columns(
        df, EXPECTED_RAW_COLUMNS, source_name="Electricity Maps"
    )

    clean_df = df.copy()

    # Normalize text fields
    clean_df["zone"] = clean_df["zone"].astype(str).str.strip()
    # zone_key may have nulls (e.g. Namibia has NaN zone_key in source data)
    clean_df["zone_key"] = clean_df["zone_key"].apply(
        lambda x: str(x).strip() if pd.notna(x) and str(x).strip() != "nan" else ""
    )
    clean_df["tier"] = clean_df["tier"].apply(
        lambda x: str(x).strip() if pd.notna(x) and str(x).strip() != "nan" else ""
    )
    clean_df["signal"] = clean_df["signal"].astype(str).str.strip()

    # Normalize timestamps to ISO-8601 UTC
    dt_series = pd.to_datetime(clean_df["available_from"], utc=True, errors="coerce")
    clean_df["available_from_utc"] = dt_series.dt.strftime("%Y-%m-%d %H:%M:%S+00:00")

    # String cleaning on other metadata fields
    for col in [
        "historical_temporal_granularity",
        "real_time_granularity",
        "forecast_source",
        "horizons",
        "forecast_granularity",
    ]:
        clean_df[col] = clean_df[col].astype(str).str.strip()

    # Add source tag
    clean_df["data_source"] = "electricity_maps"

    return clean_df[NORMALIZED_COLUMNS]


def ingest_electricity_maps(
    source_file: Optional[Path] = None,
    output_filename: str = "carbon_electricity_maps.csv",
    overwrite: bool = True,
) -> Path:
    """
    Execute Electricity Maps data ingestion pipeline.

    1. Loads the source CSV.
    2. Validates schema and non-emptiness.
    3. Normalizes text, timestamps, and column names.
    4. Deduplicates records.
    5. Deterministically sorts by ['zone', 'signal', 'available_from_utc'].
    6. Saves to data/cleaned/carbon_electricity_maps.csv.

    Args:
        source_file: Optional explicit path to raw CSV.
        output_filename: Output CSV filename.
        overwrite: Overwrite flag.

    Returns:
        Path to output file.
    """
    logger.info("Starting Electricity Maps data ingestion...")
    csv_path = resolve_electricity_maps_source(source_file)
    logger.info(f"Reading Electricity Maps data from {csv_path.name}")

    df_raw = pd.read_csv(csv_path)
    validate_non_empty(df_raw, source_name="Electricity Maps")

    df_clean = normalize_electricity_maps_dataframe(df_raw)

    # Deduplicate
    deduped = deduplicate_records(
        df_clean,
        subset=["zone", "zone_key", "signal"],
        source_name="Electricity Maps",
        logger=logger,
    )

    # Sort deterministically
    sorted_df = deduped.sort_values(
        by=["zone", "signal", "available_from_utc"]
    ).reset_index(drop=True)

    output_path = save_cleaned_dataset(
        sorted_df,
        filename=output_filename,
        overwrite=overwrite,
        logger=logger,
    )

    logger.info(
        f"Electricity Maps ingestion complete: {len(df_raw):,} raw rows -> "
        f"{len(sorted_df):,} cleaned rows across {sorted_df['zone'].nunique():,} zones."
    )
    return output_path


def main() -> None:
    """Module entry point called by the ingestion runner."""
    ingest_electricity_maps()


if __name__ == "__main__":
    main()