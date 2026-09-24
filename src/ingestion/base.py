"""Shared utilities for src/ingestion/* modules.

Every ingestion module (carbon, solar, water stress, weather), the runner in
run_ingestion.py and tests/test_ingestion.py import these helpers by name.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REAL_DATA_DIR = REPO_ROOT / "realData"
DATA_RAW_DIR = REPO_ROOT / "data" / "raw"
DATA_CLEANED_DIR = REPO_ROOT / "data" / "cleaned"


class IngestionValidationError(ValueError):
    """Raised when ingested data fails a validation check."""


class SchemaMismatchError(IngestionValidationError):
    """Raised when none of a column's candidate names are found in the source file."""


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_project_root() -> Path:
    return REPO_ROOT


def get_real_data_dir() -> Path:
    return _ensure(REAL_DATA_DIR)


def get_raw_data_dir() -> Path:
    return _ensure(DATA_RAW_DIR)


def get_cleaned_data_dir() -> Path:
    return _ensure(DATA_CLEANED_DIR)


require_dir = _ensure


# ---------------------------------------------------------------------------
# Logging (scoped to the "ingestion" logger; does not touch the root logger)
# ---------------------------------------------------------------------------


def get_ingestion_logger(name: str) -> logging.Logger:
    parent = logging.getLogger("ingestion")
    if not parent.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        parent.addHandler(handler)
        parent.setLevel(logging.INFO)
        parent.propagate = False
    return logging.getLogger(f"ingestion.{name}")


get_logger = get_ingestion_logger


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_non_empty(df: pd.DataFrame, source_name: str = "data") -> None:
    if df is None or df.empty:
        raise IngestionValidationError(f"{source_name}: dataset is empty")


def validate_required_columns(df: pd.DataFrame, required: Sequence[str], source_name: str = "data") -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise IngestionValidationError(
            f"{source_name}: missing required columns {missing}. Actual columns: {list(df.columns)}"
        )


def validate_lat_lon(
    df: pd.DataFrame, lat_col: str = "latitude", lon_col: str = "longitude", source_name: str = "data"
) -> None:
    validate_required_columns(df, [lat_col, lon_col], source_name=source_name)
    if not df[lat_col].dropna().between(-90.0, 90.0).all():
        raise IngestionValidationError(f"{source_name}: '{lat_col}' has values outside [-90, 90]")
    if not df[lon_col].dropna().between(-180.0, 180.0).all():
        raise IngestionValidationError(f"{source_name}: '{lon_col}' has values outside [-180, 180]")


def validate_numeric_range(
    df: pd.DataFrame,
    column: str,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    source_name: str = "data",
) -> None:
    """Check non-null values of `column` lie within [min_value, max_value]."""
    validate_required_columns(df, [column], source_name=source_name)
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    if min_value is not None and (values < min_value).any():
        raise IngestionValidationError(
            f"{source_name}: '{column}' has values below {min_value} (min seen {values.min()})"
        )
    if max_value is not None and (values > max_value).any():
        raise IngestionValidationError(
            f"{source_name}: '{column}' has values above {max_value} (max seen {values.max()})"
        )


def find_column(df: pd.DataFrame, candidates: Sequence[str], purpose: str) -> str:
    """Return the first column matching any candidate (case/whitespace-insensitive)."""
    normalized = {c.strip().lower(): c for c in df.columns}
    for candidate in candidates:
        key = candidate.strip().lower()
        if key in normalized:
            return normalized[key]
    raise SchemaMismatchError(
        f"Could not find a column for '{purpose}'. Tried: {list(candidates)}. Actual: {list(df.columns)}"
    )


# ---------------------------------------------------------------------------
# Transformation / output
# ---------------------------------------------------------------------------


def deduplicate_records(
    df: pd.DataFrame,
    subset: Sequence[str],
    source_name: str = "data",
    logger: Optional[logging.Logger] = None,
    keep: str = "first",
) -> pd.DataFrame:
    before = len(df)
    out = df.drop_duplicates(subset=list(subset), keep=keep).reset_index(drop=True)
    if logger is not None and len(out) != before:
        logger.info("%s: dropped %d duplicate rows (key=%s)", source_name, before - len(out), list(subset))
    return out


def save_cleaned_dataset(
    df: pd.DataFrame,
    filename: str,
    overwrite: bool = False,
    logger: Optional[logging.Logger] = None,
) -> Path:
    """Write df to data/cleaned/<filename>. Refuses to clobber unless overwrite=True."""
    out_path = get_cleaned_data_dir() / filename
    if out_path.exists() and not overwrite:
        raise FileExistsError(f"{out_path} already exists; pass overwrite=True to replace it")
    df.to_csv(out_path, index=False)
    (logger or get_ingestion_logger("base")).info("Wrote %s (%d rows, %d columns)", out_path, len(df), len(df.columns))
    return out_path


write_cleaned = lambda df, filename, logger=None: save_cleaned_dataset(df, filename, overwrite=True, logger=logger)  # noqa: E731


def list_source_files(source_dir: Path, pattern: str) -> list[Path]:
    if not source_dir.exists():
        raise FileNotFoundError(
            f"{source_dir} does not exist. Check data/external/{source_dir.name}/provenance.json "
            f"and that realData/ is present."
        )
    files = sorted(source_dir.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No files matching '{pattern}' found under {source_dir}")
    return files
