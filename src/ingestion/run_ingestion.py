"""
Data Ingestion Pipeline Runner.

Orchestrates execution of the ingestion layer modules:
1. Open-Meteo Weather (weather_open_meteo.py)
2. Electricity Maps Carbon & Grid (carbon_electricity_maps.py)
3. WRI Aqueduct Water Stress (water_stress_aqueduct.py)
4. NREL NSRDB Solar Irradiance (solar_nsrdb.py)

Usage:
    python -m src.ingestion.run_ingestion --all
    python -m src.ingestion.run_ingestion --source weather
    python -m src.ingestion.run_ingestion --source carbon
    python -m src.ingestion.run_ingestion --source water
    python -m src.ingestion.run_ingestion --source solar
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Dict, List, Optional

from .base import get_cleaned_data_dir, get_ingestion_logger
from .carbon_electricity_maps import ingest_electricity_maps
from .solar_nsrdb import (
    NSRDBConfigurationError,
    fetch_and_ingest_nsrdb,
)
from .water_stress_aqueduct import ingest_aqueduct
from .weather_open_meteo import ingest_weather

logger = get_ingestion_logger("runner")


def run_weather_pipeline() -> bool:
    """Run Open-Meteo weather ingestion."""
    try:
        t0 = time.time()
        logger.info("=== [1/4] Running Open-Meteo Weather Ingestion ===")
        out = ingest_weather()
        elapsed = time.time() - t0
        logger.info(f"Weather ingestion completed successfully in {elapsed:.2f}s -> {out.name}")
        return True
    except Exception as e:
        logger.error(f"Weather ingestion FAILED: {e}", exc_info=True)
        return False


def run_carbon_pipeline() -> bool:
    """Run Electricity Maps carbon intensity / grid coverage ingestion."""
    try:
        t0 = time.time()
        logger.info("=== [2/4] Running Electricity Maps Carbon Ingestion ===")
        out = ingest_electricity_maps()
        elapsed = time.time() - t0
        logger.info(f"Carbon ingestion completed successfully in {elapsed:.2f}s -> {out.name}")
        return True
    except Exception as e:
        logger.error(f"Carbon ingestion FAILED: {e}", exc_info=True)
        return False


def run_water_pipeline() -> bool:
    """Run WRI Aqueduct water-stress ingestion."""
    try:
        t0 = time.time()
        logger.info("=== [3/4] Running Aqueduct Water Stress Ingestion ===")
        out = ingest_aqueduct()
        elapsed = time.time() - t0
        logger.info(f"Water stress ingestion completed successfully in {elapsed:.2f}s -> {out.name}")
        return True
    except Exception as e:
        logger.error(f"Water stress ingestion FAILED: {e}", exc_info=True)
        return False


def run_solar_pipeline() -> bool:
    """Run NREL NSRDB solar irradiance ingestion."""
    try:
        t0 = time.time()
        logger.info("=== [4/4] Running NREL NSRDB Solar Ingestion ===")
        out = fetch_and_ingest_nsrdb()
        elapsed = time.time() - t0
        logger.info(f"Solar ingestion completed successfully in {elapsed:.2f}s -> {out.name}")
        return True
    except NSRDBConfigurationError as conf_err:
        logger.warning(
            f"NSRDB Solar Ingestion SKIPPED / FAILED: {conf_err}\n"
            "To enable NSRDB solar ingestion, please configure NSRDB_API_KEY in your .env file."
        )
        return False
    except Exception as e:
        logger.error(f"Solar ingestion FAILED: {e}", exc_info=True)
        return False


SOURCE_DISPATCH = {
    "weather": run_weather_pipeline,
    "carbon": run_carbon_pipeline,
    "water": run_water_pipeline,
    "solar": run_solar_pipeline,
}


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Data Centre Digital Twin - Data Ingestion Pipeline Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.ingestion.run_ingestion --all
  python -m src.ingestion.run_ingestion --source weather
  python -m src.ingestion.run_ingestion --source carbon
  python -m src.ingestion.run_ingestion --source water
  python -m src.ingestion.run_ingestion --source solar
        """,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--all",
        action="store_true",
        help="Run all ingestion pipelines (weather, carbon, water, solar)",
    )
    group.add_argument(
        "--source",
        choices=["weather", "carbon", "water", "solar"],
        help="Run a single specific ingestion source",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """
    Main entry point for ingestion runner.

    Returns:
        0 on success, 1 on failure.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    cleaned_dir = get_cleaned_data_dir()
    logger.info(f"Output directory initialized: {cleaned_dir}")

    results: Dict[str, bool] = {}

    if args.all:
        logger.info("Executing ALL ingestion pipelines...")
        for source_name, pipeline_fn in SOURCE_DISPATCH.items():
            results[source_name] = pipeline_fn()
    else:
        pipeline_fn = SOURCE_DISPATCH[args.source]
        results[args.source] = pipeline_fn()

    # Summary table
    logger.info("\n" + "=" * 50)
    logger.info("        INGESTION PIPELINE SUMMARY")
    logger.info("=" * 50)
    all_success = True
    for source, success in results.items():
        status_str = "SUCCESS" if success else "FAILED / SKIPPED"
        logger.info(f"  {source.upper():<10}: {status_str}")
        if not success:
            all_success = False
    logger.info("=" * 50)

    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())
