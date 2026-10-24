#!/usr/bin/env python3
"""Timing benchmark for the one simulator, ``src.digital_twin.DigitalTwin``.

Protocol (fixed, so numbers are comparable between runs and machines):
  * workload  : 288 steps = one simulated day, the inputs of ``generate_test_actions``
  * warm-up   : 3 untimed days (imports, caches, allocator)
  * repeats   : 30 timed days, each on a fresh twin (construction is NOT timed)
  * clock     : ``time.perf_counter``
  * reported  : median, IQR (Q3 - Q1), min, max of seconds per day and microseconds per step
  * physics   : legacy-0 and 1, both measured with this identical protocol
  * environment is printed with every result; numbers from different machines must not be mixed.

Run from the repository root:  python benchmark_performance.py [--repeats 30] [--json out.json]

This measures speed only. Output equivalence is not a question here any more: there is no second
implementation to compare against (the former "optimised" twin was retired, see docs/tasks/Task5_TWIN_PARITY_REPORT.md).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import statistics
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PHYSICS_VERSIONS = ("legacy-0", "1")
WARMUP_DAYS = 3
DEFAULT_REPEATS = 30


def generate_test_actions(n_steps=288):
    """Generate realistic test actions for 24-hour simulation."""
    actions = []

    for i in range(n_steps):
        hour = (i * 5) // 60  # 5-minute intervals

        # Server utilisation: higher during business hours
        if 8 <= hour <= 18:
            utilisation = 0.6 + 0.3 * np.sin((i - 96) * 0.1)  # Business hours
        elif 19 <= hour <= 23:
            utilisation = 0.3 + 0.2 * np.sin((i - 228) * 0.1)  # Evening
        else:  # Night
            utilisation = 0.2 + 0.1 * np.sin((i - 12) * 0.1)

        utilisation = np.clip(utilisation, 0.1, 0.9)

        # Outside temperature: daily cycle
        outside_temp = 20 + 8 * np.sin((i - 72) * np.pi / 144)  # Peak at 2pm

        # Cooling mode selection based on temperature
        if outside_temp < 12:
            cooling_mode = "free_air"
        elif outside_temp > 25:
            cooling_mode = "evaporative"
        else:
            cooling_mode = "closed_loop"

        actions.append(
            {
                "utilisation": utilisation,
                "outside_temp_C": outside_temp,
                "cooling_mode": cooling_mode,
                "humidity_pct": 45 + 15 * np.sin(i * 0.05),
                "water_pressure_bar": 2.8 + 0.4 * np.sin(i * 0.03),
            }
        )

    return actions


def environment() -> dict:
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
    }


def summarise(day_seconds: list[float], steps: int) -> dict:
    q = statistics.quantiles(day_seconds, n=4, method="inclusive")
    median = statistics.median(day_seconds)
    return {
        "repeats": len(day_seconds),
        "median_s_per_day": median,
        "iqr_s_per_day": q[2] - q[0],
        "min_s_per_day": min(day_seconds),
        "max_s_per_day": max(day_seconds),
        "median_us_per_step": median / steps * 1e6,
    }


def time_one_day(physics_version: str, actions: list[dict]) -> float:
    from src.digital_twin import DigitalTwin

    twin = DigitalTwin(physics_version=physics_version)  # construction not timed
    start = time.perf_counter()
    for action in actions:
        twin.step(action)
    return time.perf_counter() - start


def benchmark(physics_version: str, repeats: int) -> dict:
    actions = generate_test_actions()
    for _ in range(WARMUP_DAYS):
        time_one_day(physics_version, actions)
    samples = [time_one_day(physics_version, actions) for _ in range(repeats)]
    result = summarise(samples, len(actions))
    result["physics_version"] = physics_version
    result["steps_per_day"] = len(actions)
    return result


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark. It silences logging while it times things and puts the previous level back afterwards, so
    calling it from a process that keeps running (a test run, say) does not leave every logger off."""
    previous = logging.root.manager.disable
    try:
        return _run(argv)
    finally:
        logging.disable(previous)


def _run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS, help="timed days per physics version (>= 20)")
    parser.add_argument("--json", metavar="PATH", help="also write the full result as JSON")
    args = parser.parse_args(argv)
    if args.repeats < 20:
        parser.error("--repeats must be >= 20 (median/IQR are not meaningful below that)")

    logging.disable(logging.CRITICAL)  # keep the carbon-fallback warning out of the timing loop
    env = environment()
    results = [benchmark(v, args.repeats) for v in PHYSICS_VERSIONS]

    print("Digital Twin timing (DigitalTwin only; speed, not equivalence)")
    print(f"environment: {json.dumps(env)}")
    print(f"protocol   : {WARMUP_DAYS} warm-up days, {args.repeats} timed days, fresh twin per day, perf_counter")
    for r in results:
        print(
            f"  physics {r['physics_version']:<8} median {r['median_s_per_day'] * 1e3:7.3f} ms/day "
            f"(IQR {r['iqr_s_per_day'] * 1e3:6.3f} ms, min {r['min_s_per_day'] * 1e3:7.3f}, "
            f"max {r['max_s_per_day'] * 1e3:7.3f}) = {r['median_us_per_step']:6.1f} us/step"
        )
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"environment": env, "warmup_days": WARMUP_DAYS, "results": results}, fh, indent=2)
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
