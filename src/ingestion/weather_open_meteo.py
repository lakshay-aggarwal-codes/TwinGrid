"""
Open-Meteo Weather Data Ingestion Module.

Normalizes per-city hourly weather CSVs from:
realData/open_meteo/<city>_weather_2025_hourly.csv
into a single clean dataset:
data/cleaned/weather_open_meteo.csv

Handles flexible column name resolution across city files
(e.g. 'time' vs 'datetime', 'temperature_2m' vs 'temperature').
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Sequence

import pandas as pd

from .base import (
    deduplicate_records,
    get_ingestion_logger,
    get_real_data_dir,
    save_cleaned_dataset,
    validate_non_empty,
    validate_required_columns,
)

logger = get_ingestion_logger("weather_open_meteo")

SOURCE_DIR_NAME = "open_meteo"

# Candidate column names across city files for flexible resolution
TIME_CANDIDATES = ["time", "date", "datetime", "timestamp"]
TEMP_CANDIDATES = [
    "temperature_2m",
    "temperature",
    "temp_c",
    "outside_temp_c",
    "ambient_temperature_c",
]
HUMIDITY_CANDIDATES = [
    "relative_humidity_2m",
    "relative_humidity",
    "humidity",
    "humidity_pct",
    "relative_humidity_pct",
]

CITY_NAME_PATTERN = re.compile(r"^(?P<city>[a-z_]+)_weather_\d{4}_hourly\.csv$")


def _find_column(
    df: pd.DataFrame,
    candidates: Sequence[str],
    fallback_label: str,
) -> str:
    """
    Resolve a column name from a prioritized list of candidates.

    Args:
        df: DataFrame to search.
        candidates: List of possible column names (highest priority first).
        fallback_label: Human-readable label used in the error message.

    Returns:
        Matched column name.

    Raises:
        KeyError: When none of the candidates are found.
    """
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    raise KeyError(
        f"Could not resolve '{fallback_label}' column. "
        f"Tried candidates {list(candidates)}, "
        f"available columns: {list(df.columns)}"
    )


def _list_source_files(source_dir: Path, glob_pattern: str) -> List[Path]:
    """
    List source files matching a glob pattern under source_dir.

    Args:
        source_dir: Directory to search.
        glob_pattern: Glob pattern for matching files.

    Returns:
        Sorted list of matching Paths.

    Raises:
        FileNotFoundError: When no matching files are found.
    """
    files = sorted(source_dir.glob(glob_pattern))
    if not files:
        raise FileNotFoundError(
            f"No files matching '{glob_pattern}' found in {source_dir}"
        )
    return files


def city_name_from_filename(path: Path) -> str:
    """
    Extract a display-friendly city name from an Open-Meteo CSV filename.

    Args:
        path: Path to CSV file.

    Returns:
        Title-cased city name (e.g. 'new_delhi' -> 'New Delhi').
    """
    match = CITY_NAME_PATTERN.match(path.name)
    if match:
        return match.group("city").replace("_", " ").title()
    # Fall back to stem for oddly-named files
    return path.stem


def ingest_weather(
    source_dir: Optional[Path] = None,
    output_filename: str = "weather_open_meteo.csv",
    overwrite: bool = True,
) -> Path:
    """
    Execute Open-Meteo weather data ingestion pipeline.

    1. Discovers per-city hourly CSV files in realData/open_meteo/.
    2. Resolves flexible column names for timestamp, temperature, humidity.
    3. Normalizes each file into a unified schema.
    4. Concatenates, deduplicates, and sorts by [city, timestamp_utc].
    5. Saves to data/cleaned/weather_open_meteo.csv.

    Args:
        source_dir: Override path to source directory.
        output_filename: Output CSV filename.
        overwrite: Overwrite existing output flag.

    Returns:
        Path to the output file.
    """
    logger.info("Starting Open-Meteo weather data ingestion...")

    src_dir = source_dir or (get_real_data_dir() / SOURCE_DIR_NAME)
    files = _list_source_files(src_dir, "*_weather_*_hourly.csv")
    logger.info(f"Found {len(files)} city weather files in {src_dir.name}/")

    frames = []
    for path in files:
        raw = pd.read_csv(path)

        try:
            time_col = _find_column(raw, TIME_CANDIDATES, "timestamp")
            temp_col = _find_column(raw, TEMP_CANDIDATES, "outside_temp_C")
            humidity_col = _find_column(raw, HUMIDITY_CANDIDATES, "humidity_pct")
        except KeyError as e:
            logger.warning(f"Skipping {path.name}: {e}")
            continue

        cleaned = pd.DataFrame(
            {
                "city": city_name_from_filename(path),
                "timestamp_utc": pd.to_datetime(
                    raw[time_col], utc=True, errors="coerce"
                ),
                "outside_temp_C": pd.to_numeric(raw[temp_col], errors="coerce"),
                "humidity_pct": pd.to_numeric(raw[humidity_col], errors="coerce"),
            }
        )

        before = len(cleaned)
        cleaned = cleaned.dropna(
            subset=["timestamp_utc", "outside_temp_C", "humidity_pct"]
        )
        dropped = before - len(cleaned)
        if dropped:
            logger.warning(
                f"{path.name}: dropped {dropped} rows with unparseable values"
            )
        frames.append(cleaned)

    if not frames:
        raise FileNotFoundError(
            "No weather files could be parsed successfully."
        )

    combined = pd.concat(frames, ignore_index=True)
    validate_non_empty(combined, source_name="Open-Meteo Weather")

    # Deduplicate
    deduped = deduplicate_records(
        combined,
        subset=["city", "timestamp_utc"],
        source_name="Open-Meteo Weather",
        logger=logger,
    )

    # Sort deterministically
    sorted_df = deduped.sort_values(
        by=["city", "timestamp_utc"]
    ).reset_index(drop=True)

    # Add provenance
    sorted_df["data_source"] = "open_meteo"

    output_path = save_cleaned_dataset(
        sorted_df,
        filename=output_filename,
        overwrite=overwrite,
        logger=logger,
    )

    cities = sorted_df["city"].nunique()
    logger.info(
        f"Open-Meteo ingestion complete: {len(sorted_df):,} cleaned rows "
        f"across {cities} cities."
    )
    return output_path


# Wide raw schema (Open-Meteo hourly export incl. city/country/lat/lon columns).
EXPECTED_RAW_COLUMNS = [
    "timestamp",
    "city",
    "country",
    "latitude",
    "longitude",
    "ambient_temperature_c",
    "relative_humidity_pct",
    "dew_point_c",
    "apparent_temperature_c",
    "precipitation_mm",
    "cloud_cover_pct",
    "wind_speed_10m_kmh",
    "wind_direction_10m_deg",
    "solar_radiation_w_m2",
    "et0_mm",
]
_NUMERIC_WEATHER_COLUMNS = [c for c in EXPECTED_RAW_COLUMNS if c not in ("timestamp", "city", "country")]


def normalize_weather_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalise a wide Open-Meteo frame: UTC timestamps as
    "YYYY-MM-DD HH:MM:SS+00:00" strings, trimmed lower-case city/country,
    float64 numeric columns. Raises IngestionValidationError if any expected
    column is missing.

    NOTE: ingest_weather() above still uses the narrower per-city-file schema
    and does not call this function.
    """
    validate_required_columns(df, EXPECTED_RAW_COLUMNS, source_name="Open-Meteo Weather")
    out = df[EXPECTED_RAW_COLUMNS].copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce").astype(str)
    out["city"] = out["city"].astype(str).str.strip().str.lower()
    out["country"] = out["country"].astype(str).str.strip()
    for col in _NUMERIC_WEATHER_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("float64")
    return out.reset_index(drop=True)


def main() -> None:
    """Module entry point called by the ingestion runner."""
    ingest_weather()


if __name__ == "__main__":
    main()