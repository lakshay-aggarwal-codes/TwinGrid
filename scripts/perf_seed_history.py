#!/usr/bin/env python3
"""Task 29: store >= 5,000 SIMULATOR-produced samples per feature sensor so history queries can be timed.

    python scripts\\perf_seed_history.py --ticks 5000 --stream import:perf-2026-10

Every value comes from ``DigitalTwin.step`` (the same call the live loop makes); nothing is hand-written. What is NOT
live: the event times are back-dated, one tick every ``--interval-s`` seconds, ending now, and the utilisation / outside
temperature inputs follow a fixed deterministic daily pattern (not a recorded workload). Samples go in through the real
``ingest_samples`` (validation, dedupe, unique constraint) with ``origin='simulated'`` on the stream you name, so they do
not mix with the ``live`` stream. Needs the database to be up and the five ``fac<id>.<feature>`` sensors seeded
(``scripts/seed_facility.py --seed-sensors``). Prints stored / rejected counts; nothing is assumed to have been stored.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BATCH_TICKS = 200  # 200 ticks x 5 sensors = 1000 samples = the ingest batch limit


async def main(ticks: int, interval_s: float, stream: str) -> int:
    from api import config
    from database import get_session
    from src.digital_twin import DigitalTwin
    from src.telemetry.ingest import ingest_samples

    mapping = config.telemetry_feature_sensors()
    twin = DigitalTwin()
    end = datetime.now(timezone.utc).replace(microsecond=0)
    start = end - timedelta(seconds=interval_s * ticks)
    stored = rejected = 0
    reasons: dict[str, int] = {}
    batch: list[dict] = []

    async def flush() -> None:
        nonlocal stored, rejected, batch
        if not batch:
            return
        async with get_session() as session:
            result = await ingest_samples(session, batch, stream_id=stream, origin="simulated")
            await session.commit()
        stored += result.stored
        rejected += len(batch) - result.stored
        for code, n in result.counts.items():
            if n and code != "accepted":
                reasons[code] = reasons.get(code, 0) + n
        batch = []

    for i in range(ticks):
        hour = (i * interval_s / 3600.0) % 24.0
        utilisation = 0.55 + 0.25 * math.sin(2 * math.pi * (hour - 9) / 24)  # fixed daily pattern, 0.30 .. 0.80
        outside = 22.0 + 6.0 * math.sin(2 * math.pi * (hour - 15) / 24)
        mode = twin.select_cooling_mode(outside, 0.1)
        state = twin.step(
            {"utilisation": utilisation, "outside_temp_C": outside, "water_stress": 0.1, "cooling_mode": mode}
        ).to_dict()
        ts = start + timedelta(seconds=interval_s * (i + 1))
        for feature, external_id in mapping.items():
            batch.append(
                {
                    "external_id": external_id,
                    "ts_event": ts,
                    "value": float(state[feature]),
                    "sim_time": state["timestamp"],
                }
            )
        if (i + 1) % BATCH_TICKS == 0:
            await flush()
    await flush()
    print(f"ticks={ticks} stream={stream} stored={stored} not_stored={rejected} reasons={reasons or '{}'}")
    return 0 if stored else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ticks", type=int, default=5000, help="ticks per sensor (5 sensors are written per tick)")
    ap.add_argument("--interval-s", type=float, default=3.0)
    ap.add_argument("--stream", default="import:perf-2026-10")
    a = ap.parse_args()
    if a.ticks < 1:
        ap.error("--ticks must be >= 1")
    sys.exit(asyncio.run(main(a.ticks, a.interval_s, a.stream)))
