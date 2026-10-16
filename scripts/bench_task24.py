"""Task 24 micro-benchmark. Needs only numpy/pandas (no FastAPI, Redis or database): ``python scripts/bench_task24.py``.

It measures what it can run in-process and says what it cannot: no Redis round trip, no HTTP stack, no database.
The carbon-load row uses a SYNTHETIC 8,760-row hourly file (the repo ships no carbon data); the state row uses the
project's real loader, so it reports whichever of the real file or the labelled flat fallback is present.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

from api.services import scenario_registry  # noqa: E402
from src import carbon_provider as cp  # noqa: E402
from src.digital_twin import DigitalTwin  # noqa: E402
from src.perf.cache import ResponseCache  # noqa: E402
from src.perf.etag import ETagMiddleware, compute_etag  # noqa: E402


def median_ms(fn, n: int) -> float:
    xs = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t) * 1e3)
    return statistics.median(xs)


class _Dict:
    def __init__(self):
        self.d: dict[str, str] = {}

    def mget(self, keys):
        return [self.d.get(k) for k in keys]

    def set(self, k, v, ttl_ms):
        self.d[k] = v

    def incr(self, k):
        self.d[k] = str(int(self.d.get(k, "0")) + 1)


def asgi_per_request_us(app, headers, n: int = 3000) -> float:
    scope = {"type": "http", "method": "GET", "path": "/api/scenarios", "headers": headers}

    async def receive():
        return {"type": "http.request"}

    async def send(_):
        pass

    async def loop():
        t = time.perf_counter()
        for _ in range(n):
            await app(scope, receive, send)
        return (time.perf_counter() - t) / n * 1e6

    return asyncio.run(loop())


def main() -> None:
    rows: list[tuple[str, str]] = []
    payload = json.dumps(scenario_registry.list_scenarios(), separators=(",", ":")).encode()
    gz = gzip.compress(payload, compresslevel=6)
    ratio = len(gz) / len(payload)
    rows.append(("/api/scenarios payload", f"{len(payload)} B plain, {len(gz)} B gzip level 6 ({ratio:.0%})"))
    compute_us = median_ms(scenario_registry.list_scenarios, 2000) * 1e3
    rows.append(("list_scenarios() compute", f"{compute_us:.0f} us median"))

    def one_state():
        t = DigitalTwin()
        mode = t.select_cooling_mode(25.0, 0.0)
        t.step({"utilisation": 0.5, "outside_temp_C": 25.0, "water_stress": 0.0, "cooling_mode": mode})

    one_state()
    _, real = cp.load_diurnal_carbon_intensity()
    state_ms = median_ms(one_state, 300)
    rows.append((f"state preview (new DigitalTwin + step), carbon file present: {real}", f"{state_ms:.3f} ms median"))

    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "carbon_intensity.csv"
        t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        f.write_text(
            "timestamp_utc,zone,carbon_intensity_gco2_per_kwh\n"
            + "\n".join(f"{(t0 + timedelta(hours=i)).isoformat()},ZZ,{300 + i % 24 * 7}" for i in range(8760)),
            encoding="utf-8",
        )
        cold = median_ms(lambda: cp._load_carbon_signal_uncached(path=f), 5)
        cp.clear_carbon_cache()
        cp.load_carbon_signal(path=f)
        warm = median_ms(lambda: cp.load_carbon_signal(path=f), 200)
        rows.append(("carbon load, synthetic 8,760-row file: parse every time (before)", f"{cold:.2f} ms median"))
        rows.append(("carbon load, same file: memoised (after, includes hashing the file)", f"{warm:.3f} ms median"))

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": payload})

    wrapped = ETagMiddleware(app)
    plain = asgi_per_request_us(app, [])
    full = asgi_per_request_us(wrapped, [])
    cond = asgi_per_request_us(wrapped, [(b"if-none-match", compute_etag(payload).encode())])
    rows.append(("ASGI handler, plain (no middleware)", f"{plain:.1f} us/request"))
    rows.append(("ASGI handler + ETag middleware, 200", f"{full:.1f} us/request"))
    rows.append((f"ASGI handler + ETag middleware, 304 (bytes sent: 0 vs {len(payload)})", f"{cond:.1f} us/request"))

    cache = ResponseCache(_Dict())
    cache.get_or_compute("s", ["k"], 1, scenario_registry.list_scenarios)
    hit_us = median_ms(lambda: cache.get_or_compute("s", ["k"], 1, scenario_registry.list_scenarios), 2000) * 1e3
    rows.append(("ResponseCache hit, in-memory dict backend (NO Redis, no network)", f"{hit_us:.0f} us median"))

    print("| measurement | result |\n|---|---|")
    for k, v in rows:
        print(f"| {k} | {v} |")
    print("\nNOT MEASURED: Redis round trip, HTTP stack, database queries, index effect, behaviour under concurrency.")


if __name__ == "__main__":
    main()
