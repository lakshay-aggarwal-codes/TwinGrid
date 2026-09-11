"""
Shared utilities for the Digital Twin data ingestion layer.

Provides path resolution, logging, validation, safe dataset serialization,
and deduplication helpers for all ingestion modules.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence, Union

import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# -----------------------------------------------------------------------------
# Path Resolution Helpers
# -----------------------------------------------------------------------------


def get_project_root() -> Path:
    """Return the absolute path to the project root directory."""
    # base.py is located at <project_root>/src/ingestion/base.py
    return Path(__file__).resolve().parent.parent.parent


def get_real_data_dir() -> Path:
    """Return path to realData/ directory where raw 3rd-party datasets live."""
    return get_project_root() / "realData"


def get_raw_data_dir() -> Path:
    """Return path to data/raw/ directory."""
    return get_project_root() / "data" / "raw"


def get_cleaned_data_dir() -> Path:
    """Return path to data/cleaned/ directory, creating it if needed."""
    cleaned_dir = get_project_root() / "data" / "cleaned"
    cleaned_dir.mkdir(parents=True, exist_ok=True)
    return cleaned_dir


# -----------------------------------------------------------------------------
# Logging Helper
# -----------------------------------------------------------------------------


def get_ingestion_logger(name: str) -> logging.Logger:
    """
    Configure and return a standardized logger for ingestion modules.

    Args:
        name: Logger name (typically __name__ or module name).

    Returns:
        logging.Logger instance.
    """
    logger = logging.getLogger(f"ingestion.{name}")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)

        # Optional: write to logs/ingestion.log if logs/ exists or can be created
        log_dir = get_project_root() / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(
                log_dir / "ingestion.log", encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logging.INFO)
            logger.addHandler(file_handler)
        except Exception:
            pass  # Fallback gracefully to console logging

    return logger


# -----------------------------------------------------------------------------
# Validation Helpers
# -----------------------------------------------------------------------------


class IngestionValidationError(ValueError):
    """Raised when data fails ingestion validation checks."""

    pass


def validate_non_empty(df: pd.DataFrame, source_name: str) -> None:
    """
    Validate that the DataFrame is not empty.

    Args:
        df: DataFrame to validate.
        source_name: Source name for error context.
    """
    if df is None or len(df) == 0:
        raise IngestionValidationError(
            f"[{source_name}] Ingestion failed: dataset is empty (0 rows)."
        )


def validate_required_columns(
    df: pd.DataFrame,
    required_columns: Sequence[str],
    source_name: str,
) -> None:
    """
    Validate that all required columns are present in the DataFrame.

    Args:
        df: DataFrame to check.
        required_columns: List or sequence of expected column names.
        source_name: Name of the ingestion source.
    """
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise IngestionValidationError(
            f"[{source_name}] Schema validation failed. Missing required columns: {missing}. "
            f"Present columns: {list(df.columns)}"
        )


def validate_lat_lon(
    df: pd.DataFrame,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
    source_name: str = "coordinates",
) -> None:
    """
    Validate that latitude is in [-90, 90] and longitude is in [-180, 180].

    Args:
        df: DataFrame with coordinates.
        lat_col: Latitude column name.
        lon_col: Longitude column name.
        source_name: Ingestion source name.
    """
    if lat_col in df.columns:
        invalid_lat = df[(df[lat_col] < -90.0) | (df[lat_col] > 90.0)]
        if not invalid_lat.empty:
            raise IngestionValidationError(
                f"[{source_name}] Invalid latitude values found out of [-90, 90]: "
                f"{invalid_lat[lat_col].iloc[0]}"
            )
    if lon_col in df.columns:
        invalid_lon = df[(df[lon_col] < -180.0) | (df[lon_col] > 180.0)]
        if not invalid_lon.empty:
            raise IngestionValidationError(
                f"[{source_name}] Invalid longitude values found out of [-180, 180]: "
                f"{invalid_lon[lon_col].iloc[0]}"
            )


def validate_numeric_range(
    df: pd.DataFrame,
    column: str,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    source_name: str = "numeric_check",
) -> None:
    """
    Validate that numeric values in a column fall within bounds (ignoring NaNs).

    Args:
        df: DataFrame to check.
        column: Column name.
        min_value: Minimum allowed value.
        max_value: Maximum allowed value.
        source_name: Source name.
    """
    if column not in df.columns:
        return
    valid_series = pd.to_numeric(df[column], errors="coerce").dropna()
    if min_value is not None:
        below_min = valid_series[valid_series < min_value]
        if not below_min.empty:
            raise IngestionValidationError(
                f"[{source_name}] Column '{column}' has values below minimum {min_value}: "
                f"{below_min.iloc[0]}"
            )
    if max_value is not None:
        above_max = valid_series[valid_series > max_value]
        if not above_max.empty:
            raise IngestionValidationError(
                f"[{source_name}] Column '{column}' has values above maximum {max_value}: "
                f"{above_max.iloc[0]}"
            )


def deduplicate_records(
    df: pd.DataFrame,
    subset: Optional[List[str]] = None,
    source_name: str = "source",
    logger: Optional[logging.Logger] = None,
) -> pd.DataFrame:
    """
    Deduplicate DataFrame rows, logging the count of removed duplicates.

    Args:
        df: Input DataFrame.
        subset: Column subset for identifying duplicates, or None for all columns.
        source_name: Source identifier for logs.
        logger: Optional logger.

    Returns:
        Deduplicated DataFrame.
    """
    initial_rows = len(df)
    df_dedup = df.drop_duplicates(subset=subset).copy()
    dropped = initial_rows - len(df_dedup)
    if dropped > 0 and logger:
        logger.info(
            f"[{source_name}] Removed {dropped:,} duplicate records (retained {len(df_dedup):,} rows)."
        )
    return df_dedup


# -----------------------------------------------------------------------------
# File Output Utilities
# -----------------------------------------------------------------------------


def save_cleaned_dataset(
    df: pd.DataFrame,
    filename: Union[str, Path],
    overwrite: bool = True,
    logger: Optional[logging.Logger] = None,
) -> Path:
    """
    Safely write a normalized DataFrame to data/cleaned/<filename>.

    Guarantees:
    - Target directory data/cleaned/ is used.
    - Never writes into realData/ or data/raw/.
    - Protects against accidental overwrites if overwrite=False.
    - Uses UTF-8 encoding.

    Args:
        df: Normalized DataFrame.
        filename: Destination filename (e.g. 'weather_open_meteo.csv').
        overwrite: Whether to overwrite existing target file.
        logger: Optional logger for progress reporting.

    Returns:
        Path to the saved CSV file.
    """
    cleaned_dir = get_cleaned_data_dir()
    target_path = (cleaned_dir / Path(filename).name).resolve()

    # Safety check: ensure target is strictly inside data/cleaned
    if not str(target_path).startswith(str(cleaned_dir.resolve())):
        raise ValueError(
            f"Unsafe destination path {target_path}: must be inside {cleaned_dir}"
        )

    # Protect against raw data overwriting
    real_data_dir = get_real_data_dir().resolve()
    raw_data_dir = get_raw_data_dir().resolve()
    if str(target_path).startswith(str(real_data_dir)) or str(
        target_path
    ).startswith(str(raw_data_dir)):
        raise ValueError(
            f"Safety violation: Attempted to write cleaned data to raw directory {target_path}"
        )

    if target_path.exists() and not overwrite:
        raise FileExistsError(
            f"Target file {target_path} already exists and overwrite is set to False."
        )

    # Write CSV safely
    df.to_csv(target_path, index=False, encoding="utf-8")
    if logger:
        logger.info(
            f"Saved {len(df):,} cleaned rows to {target_path.relative_to(get_project_root())}"
        )

    return target_path
