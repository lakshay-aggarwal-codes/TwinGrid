# Task 24 report: backend performance

## What changed
- **Carbon-file memo (`src/carbon_provider.py`)**: every `/api/state` call builds a `DigitalTwin`, which re-read and re-parsed the whole carbon file. Repeat loads of an unchanged file are now memoised under a hash of the file and sidecar bytes (plus zone and site time zone); a missing file is never cached; the curve is returned as a copy. Numbers are identical.
- **ETag / 304 + gzip (`api/plugins/performance.py`, `src/perf/etag.py`)**: weak ETag on `/api/scenarios`, `/api/state`, `/api/whatif`, `/api/benchmark`, `/api/simulate/*`; the route and its auth always run first. Starlette gzip above 1 KiB.
- **Response cache (`src/perf/cache.py`)**: JSON-only, one `MGET` per lookup, generation-based `invalidate(ns)`, fail-open with a breaker. **Off by default** (see Assumptions).
- **Indexes (migration `20261007000000`, additive)**: `alerts(created_at, id)` and `optimizer_proposals(status, created_at, id)` for the newest-first list queries. ORM updated so `alembic check` stays clean; `tests/test_alembic_chain.py` head moved to the new revision (as Task 19 did).
- **Pagination guard (`src/perf/pagination.py`)**: every page-size query parameter in the OpenAPI spec must declare a maximum (<= 5000). The audit found none missing.
- `scripts/bench_task24.py`; env vars in `docs/env/Task24.md`.

## Assumptions
- The response cache is opt-in (`PERF_CACHE_NAMESPACES`) because measured compute is already below a Redis round trip (below), so turning it on by default would likely slow requests down. Without Redis behaviour is unchanged.
- ETag only yields 304s when the body is stable: `/api/scenarios` is; `/api/state` carries a fresh timestamp, so it only repeats inside the cache TTL.
- **Found, not changed:** `telemetry_window.load_store_series` runs one query per feature sensor (5 small queries on the unique index, per scoring tick). A single window-function query would fix it, but I cannot execute SQL here and the function fails closed, so I left it.

## Measured here (`python scripts/bench_task24.py`, numbers are from this sandbox only)
- Carbon load, **synthetic** 8,760-row file: 29.76 ms parsed each time -> 0.225 ms memoised.
- `list_scenarios()` 76 us; state preview 0.075 ms (flat-fallback carbon, no data file in this repo copy); scenarios payload 4240 B -> 704 B gzip.
- ETag middleware 7.1 us/request (200), 9.1 us (304, 0 body bytes vs 4240); in-memory cache hit 26 us.
- NOT MEASURED: Redis round trip, HTTP stack, DB query plans or index effect, concurrency. No SLO is claimed.

## Test results
- `tests/test_task24_perf.py`: `passed 39, failed 0` (run with a small stand-in runner, since pytest is not installed here; breaking the cache invalidation or the content hash makes it fail). Existing carbon tests that can run here fail identically with the original and the edited file (missing data/modules).

## Not verified
- `pytest`, `ruff`, `alembic check`/round trip, and `tests/api/test_task24_perf_api.py` (gzip, 304 over HTTP, cache wiring, OpenAPI guard) were NOT run: no FastAPI, SQLAlchemy, pytest or network in this sandbox.
