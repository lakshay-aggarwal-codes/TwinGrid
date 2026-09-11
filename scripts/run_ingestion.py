#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingestion import (  # noqa: E402
    carbon_electricity_maps,
    solar_nsrdb,
    water_stress_aqueduct,
    weather_open_meteo,
)

MODULES = {
    "weather_open_meteo": weather_open_meteo,
    "carbon_electricity_maps": carbon_electricity_maps,
    "water_stress_aqueduct": water_stress_aqueduct,
    "solar_nsrdb": solar_nsrdb,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", choices=list(MODULES.keys()))
    args = parser.parse_args()

    targets = args.only or list(MODULES.keys())
    failures = []
    for name in targets:
        print(f"\n=== {name} ===")
        try:
            MODULES[name].main()
        except Exception as exc:  # noqa: BLE001 -- intentional: isolate per-source failures
            print(f"FAILED: {name}: {exc}")
            failures.append(name)

    print("\n--- Summary ---")
    for name in targets:
        status = "FAILED" if name in failures else "OK"
        print(f"{name}: {status}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())