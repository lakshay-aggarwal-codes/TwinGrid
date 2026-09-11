"""
NREL NSRDB Solar Irradiance Ingestion Module.

Fetches high-resolution solar irradiance and meteorological data from the
National Renewable Energy Laboratory (NREL) National Solar Radiation Database (NSRDB)
API (Physical Solar Model - PSM v3 download service) for a configurable facility location.

Features:
- Configurable coordinates, year, attributes via environment or arguments
- API key validation and safe scrubbing (never logs secrets)
- Exponential backoff retry for HTTP rate limits (429) and transient network drops
- Robust parsing of NSRDB CSV format (skips parameter header metadata)
- Output normalized to data/cleaned/solar_nsrdb.csv
"""

from __future__ import annotations

import io
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
from dotenv import load_dotenv

from .base import (
    deduplicate_records,
    get_ingestion_logger,
    save_cleaned_dataset,
    validate_lat_lon,
    validate_non_empty,
    validate_numeric_range,
    validate_required_columns,
)

load_dotenv()

logger = get_ingestion_logger("solar_nsrdb")

# NREL NSRDB PSM3 endpoint
NSRDB_API_BASE_URL = "https://developer.nrel.gov/api/nsrdb/v2/solar/psm3-download.csv"

# Default attributes requested from NSRDB
DEFAULT_ATTRIBUTES = (
    "ghi,dni,dhi,air_temperature,relative_humidity,dew_point,wind_speed,wind_direction,surface_pressure"
)

# Standardized columns expected in the normalized output
NORMALIZED_COLUMNS = [
    "timestamp",
    "latitude",
    "longitude",
    "ghi_w_m2",
    "dni_w_m2",
    "dhi_w_m2",
    "air_temperature_c",
    "relative_humidity_pct",
    "dew_point_c",
    "wind_speed_m_s",
    "wind_direction_deg",
    "surface_pressure_mbar",
    "facility_lat",
    "facility_lon",
    "data_source",
]


class NSRDBConfigurationError(ValueError):
    """Raised when NSRDB credentials or parameters are missing/invalid."""

    pass


class NSRDBAPIError(RuntimeError):
    """Raised when the NREL NSRDB API returns an error response."""

    pass


def get_nsrdb_config(
    api_key: Optional[str] = None,
    email: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    year: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Load and validate NSRDB configuration from arguments or environment variables.

    Environment variables:
        NSRDB_API_KEY
        NSRDB_EMAIL
        NSRDB_LATITUDE
        NSRDB_LONGITUDE
        NSRDB_YEAR
    """
    key = api_key or os.getenv("NSRDB_API_KEY")
    if not key or key.strip() == "" or "your-api-key" in key.lower():
        raise NSRDBConfigurationError(
            "NSRDB API key is missing. Set NSRDB_API_KEY in your .env file or environment, "
            "or pass api_key to fetch_and_ingest_nsrdb(). "
            "Sign up for a free key at https://developer.nrel.gov/signup/"
        )

    user_email = email or os.getenv("NSRDB_EMAIL", "digitaltwin@example.com")

    # Coordinates (default to Delhi data centre coordinates if not specified)
    lat_val = latitude if latitude is not None else os.getenv("NSRDB_LATITUDE", "28.6139")
    lon_val = longitude if longitude is not None else os.getenv("NSRDB_LONGITUDE", "77.2090")

    try:
        lat = float(lat_val)
    except (ValueError, TypeError):
        raise NSRDBConfigurationError(f"Invalid latitude value: {lat_val}")

    try:
        lon = float(lon_val)
    except (ValueError, TypeError):
        raise NSRDBConfigurationError(f"Invalid longitude value: {lon_val}")

    # Validate coordinate bounds
    if not (-90.0 <= lat <= 90.0):
        raise NSRDBConfigurationError(f"Latitude must be in [-90, 90], got: {lat}")
    if not (-180.0 <= lon <= 180.0):
        raise NSRDBConfigurationError(f"Longitude must be in [-180, 180], got: {lon}")

    # Year (NSRDB historical PSM3 data is available up to 2022/2023)
    year_val = year if year is not None else os.getenv("NSRDB_YEAR", "2020")
    try:
        yr = int(year_val)
    except (ValueError, TypeError):
        raise NSRDBConfigurationError(f"Invalid year value: {year_val}")

    if yr < 1998 or yr > 2024:
        raise NSRDBConfigurationError(
            f"NSRDB PSM3 typically covers years 1998 to 2023. Got: {yr}"
        )

    return {
        "api_key": key.strip(),
        "email": user_email.strip(),
        "latitude": lat,
        "longitude": lon,
        "year": yr,
    }


def fetch_nsrdb_raw_data(
    config: Dict[str, Any],
    timeout: int = 30,
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    session: Optional[requests.Session] = None,
) -> str:
    """
    Execute HTTP request to NREL NSRDB API with backoff retry and error handling.
    NEVER logs or exposes the API key.

    Args:
        config: Dict from get_nsrdb_config().
        timeout: Request timeout in seconds.
        max_retries: Maximum number of retries on 429/5xx.
        backoff_factor: Exponential backoff factor.
        session: Optional requests.Session for testing.

    Returns:
        Raw CSV text response.
    """
    http = session or requests.Session()

    params = {
        "api_key": config["api_key"],
        "email": config["email"],
        "lat": config["latitude"],
        "lon": config["longitude"],
        "names": str(config["year"]),
        "interval": "60",  # hourly resolution
        "attributes": DEFAULT_ATTRIBUTES,
        "leap_day": "true",
        "utc": "true",
    }

    # Scrubbed URL for logging
    safe_params = {k: ("***" if k == "api_key" else v) for k, v in params.items()}
    logger.info(
        f"Requesting NSRDB solar data for lat={config['latitude']}, lon={config['longitude']}, year={config['year']} "
        f"(API key scrubbed)."
    )

    attempt = 0
    delay = 1.0

    while attempt < max_retries:
        attempt += 1
        try:
            resp = http.get(NSRDB_API_BASE_URL, params=params, timeout=timeout)

            # Handle rate limiting
            if resp.status_code == 429:
                logger.warning(
                    f"NSRDB API rate limit exceeded (429). Retrying attempt {attempt}/{max_retries} in {delay:.1f}s..."
                )
                time.sleep(delay)
                delay *= backoff_factor
                continue

            # Handle authentication / forbidden
            if resp.status_code in (401, 403):
                raise NSRDBAPIError(
                    f"NSRDB API authentication error (HTTP {resp.status_code}): "
                    "Invalid or unapproved API key. Verify your key at https://developer.nrel.gov/"
                )

            # Handle bad request
            if resp.status_code == 400:
                raise NSRDBAPIError(
                    f"NSRDB API returned bad request (HTTP 400): {resp.text[:300]}"
                )

            # Raise other HTTP errors
            resp.raise_for_status()

            # Successful response
            logger.info(
                f"NSRDB API responded successfully (HTTP {resp.status_code}, {len(resp.content):,} bytes)."
            )
            return resp.text

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as net_err:
            logger.warning(
                f"NSRDB network error on attempt {attempt}/{max_retries}: {net_err}. Retrying in {delay:.1f}s..."
            )
            if attempt >= max_retries:
                raise NSRDBAPIError(
                    f"Failed to connect to NSRDB API after {max_retries} attempts: {net_err}"
                )
            time.sleep(delay)
            delay *= backoff_factor

    raise NSRDBAPIError(
        f"NSRDB API request failed after {max_retries} retry attempts."
    )


def normalize_nsrdb_raw_text(
    csv_text: str, facility_lat: float, facility_lon: float
) -> pd.DataFrame:
    """
    Parse and normalize NSRDB raw CSV output.

    NSRDB CSV files have metadata in row 0/1 (e.g. Source, Location ID, Elevation),
    followed by the actual header row starting with Year, Month, Day, Hour, Minute.

    Args:
        csv_text: Raw string returned from NSRDB API.
        facility_lat: Facility latitude.
        facility_lon: Facility longitude.

    Returns:
        Normalized DataFrame.
    """
    lines = csv_text.strip().splitlines()
    if not lines:
        raise NSRDBAPIError("NSRDB returned an empty response body.")

    # Find the header row (contains Year, Month, Day)
    header_idx = -1
    for idx, line in enumerate(lines[:10]):
        lower_line = line.lower()
        if "year" in lower_line and "month" in lower_line and "day" in lower_line:
            header_idx = idx
            break

    if header_idx == -1:
        raise NSRDBAPIError(
            f"Could not locate data header in NSRDB response. Preview: {lines[:3]}"
        )

    # Parse CSV starting from header row
    data_stream = io.StringIO("\n".join(lines[header_idx:]))
    df = pd.read_csv(data_stream)

    # Standardize column names to lowercase
    df.columns = [c.strip().lower() for c in df.columns]

    # Required time columns
    time_cols = ["year", "month", "day", "hour", "minute"]
    validate_required_columns(df, time_cols, source_name="NSRDB Time Columns")

    # Construct ISO-8601 UTC timestamp
    df["timestamp"] = pd.to_datetime(
        dict(
            year=df["year"],
            month=df["month"],
            day=df["day"],
            hour=df["hour"],
            minute=df["minute"],
        ),
        utc=True,
    ).dt.strftime("%Y-%m-%d %H:%M:%S+00:00")

    # Map variables to standard schema
    col_mapping = {
        "ghi": "ghi_w_m2",
        "dni": "dni_w_m2",
        "dhi": "dhi_w_m2",
        "temperature": "air_temperature_c",
        "air_temperature": "air_temperature_c",
        "relative_humidity": "relative_humidity_pct",
        "dew_point": "dew_point_c",
        "wind_speed": "wind_speed_m_s",
        "wind_direction": "wind_direction_deg",
        "surface_pressure": "surface_pressure_mbar",
        "pressure": "surface_pressure_mbar",
    }

    clean_df = pd.DataFrame()
    clean_df["timestamp"] = df["timestamp"]
    clean_df["latitude"] = float(facility_lat)
    clean_df["longitude"] = float(facility_lon)

    for src_col, target_col in col_mapping.items():
        if src_col in df.columns:
            clean_df[target_col] = pd.to_numeric(df[src_col], errors="coerce")
        elif target_col not in clean_df.columns:
            clean_df[target_col] = 0.0

    # Ensure required radiation fields exist
    for rad_field in ["ghi_w_m2", "dni_w_m2", "dhi_w_m2"]:
        if rad_field not in clean_df.columns:
            clean_df[rad_field] = 0.0

    clean_df["facility_lat"] = float(facility_lat)
    clean_df["facility_lon"] = float(facility_lon)
    clean_df["data_source"] = "nrel_nsrdb_psm3"

    # Validation
    validate_numeric_range(
        clean_df, "ghi_w_m2", min_value=0.0, max_value=2000.0, source_name="NSRDB GHI"
    )
    validate_numeric_range(
        clean_df, "dni_w_m2", min_value=0.0, max_value=2000.0, source_name="NSRDB DNI"
    )
    validate_numeric_range(
        clean_df, "dhi_w_m2", min_value=0.0, max_value=2000.0, source_name="NSRDB DHI"
    )

    return clean_df[NORMALIZED_COLUMNS]


def fetch_and_ingest_nsrdb(
    api_key: Optional[str] = None,
    email: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    year: Optional[int] = None,
    output_filename: str = "solar_nsrdb.csv",
    overwrite: bool = True,
    session: Optional[requests.Session] = None,
) -> Path:
    """
    End-to-end NSRDB solar data fetch and ingestion.

    1. Validates configuration and API key.
    2. Issues HTTP request to NREL NSRDB PSM3 endpoint.
    3. Normalizes returned irradiance and meteorological records.
    4. Deduplicates and sorts deterministically by timestamp.
    5. Saves to data/cleaned/solar_nsrdb.csv.

    Args:
        api_key: NREL API key (optional if NSRDB_API_KEY in env).
        email: Registered email.
        latitude: Facility latitude.
        longitude: Facility longitude.
        year: Year to fetch.
        output_filename: Output CSV filename.
        overwrite: Overwrite flag.
        session: Optional requests.Session for mocking/testing.

    Returns:
        Path to output file.
    """
    logger.info("Starting NREL NSRDB Solar data ingestion...")
    config = get_nsrdb_config(
        api_key=api_key,
        email=email,
        latitude=latitude,
        longitude=longitude,
        year=year,
    )

    raw_csv = fetch_nsrdb_raw_data(config, session=session)
    clean_df = normalize_nsrdb_raw_text(
        raw_csv,
        facility_lat=config["latitude"],
        facility_lon=config["longitude"],
    )

    validate_non_empty(clean_df, source_name="NSRDB Solar")

    # Deduplicate and sort
    deduped = deduplicate_records(
        clean_df,
        subset=["timestamp", "latitude", "longitude"],
        source_name="NSRDB Solar",
        logger=logger,
    )
    sorted_df = deduped.sort_values(by=["timestamp"]).reset_index(drop=True)

    output_path = save_cleaned_dataset(
        sorted_df,
        filename=output_filename,
        overwrite=overwrite,
        logger=logger,
    )

    logger.info(
        f"NSRDB solar ingestion complete: {len(sorted_df):,} hourly records "
        f"for ({config['latitude']}, {config['longitude']}) year {config['year']} saved."
    )
    return output_path


def main() -> None:
    """Module entry point called by the ingestion runner."""
    fetch_and_ingest_nsrdb()


if __name__ == "__main__":
    main()
