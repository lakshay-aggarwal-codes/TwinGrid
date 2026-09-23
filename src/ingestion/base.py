"""Shared utilities for src/ingestion/* modules."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REAL_DATA_DIR = REPO_ROOT / "realData"
DATA_CLEANED_DIR = REPO_ROOT / "data" / "cleaned"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class SchemaMismatchError(Exception):
    """Raised when none of a column's candidate names are found in the source file.

    Deliberately verbose: prints every column that WAS found, so fixing this
    is a one-line edit to the candidate list, not a debugging session.
    """


def find_column(df: pd.DataFrame, candidates: Sequence[str], purpose: str) -> str:
    """Return the first column in `df` matching any name in `candidates`
    (case-insensitive, whitespace-insensitive). Raises SchemaMismatchError
    with the full actual column list if none match.
    """
    normalized = {c.strip().lower(): c for c in df.columns}
    for candidate in candidates:
        key = candidate.strip().lower()
        if key in normalized:
            return normalized[key]
    raise SchemaMismatchError(
        f"Could not find a column for '{purpose}'. Tried candidates: {list(candidates)}. "
        f"Actual columns in file: {list(df.columns)}. "
        f"Fix: add the real column name to the candidate list in this ingestion module."
    )


def require_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_cleaned(df: pd.DataFrame, filename: str, logger: logging.Logger) -> Path:
    require_dir(DATA_CLEANED_DIR)
    out_path = DATA_CLEANED_DIR / filename
    df.to_csv(out_path, index=False)
    logger.info("Wrote %s (%d rows, %d columns)", out_path, len(df), len(df.columns))
    return out_path


def list_source_files(source_dir: Path, pattern: str) -> list[Path]:
    if not source_dir.exists():
        raise FileNotFoundError(
            f"{source_dir} does not exist. Check data/external/{source_dir.name}/provenance.json "
            f"to confirm this source was scanned in Phase 1, and that realData/ is present."
        )
    files = sorted(source_dir.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No files matching '{pattern}' found under {source_dir}")
    return files