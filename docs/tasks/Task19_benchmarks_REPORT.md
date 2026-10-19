# Task 19 (roadmap): measure before optimising: PASS 1 (measurement suite; no optimisation)

(Named `Task19_benchmarks_REPORT.md`; `Task19_REPORT.md` is an earlier, different task.)

## Dependencies
Task 5 (retired `DigitalTwinOptimized`: `Task5_TWIN_PARITY_REPORT.md`) and Task 8 (carbon signal: `Task8_carbon_signal_REPORT.md`) are in the tree.

## Delivered
`scripts/bench_suite.py` (measures only; writes only the JSON you name) and `tests/test_bench_suite.py` (9 tests).

| Section | What is timed | Needs |
|---|---|---|
| `twin` | `DigitalTwin.step`, one simulated day (288 steps) per sample, legacy-0 and physics 1, fresh twin per sample | numpy |
| `env` | `DataCentreEnv` reset + 288 steps, physics 1 | gymnasium |
| `episode` | one `run_episode` (rule policy, physics 1) including environment construction: the unit an evaluation multiplies | gymnasium |
| `api` | GET latency and payload size (identity bytes, gzip estimate) for `/healthz`, `/api/state`, `/api/scenarios`, `/api/evaluations` | a running API; `TWINGRID_USERNAME`/`TWINGRID_PASSWORD` in the environment (never argv) |

Protocol: 3 warm-up then 20 timed samples (a lower `--repeats` is refused), `perf_counter`, reported n / median / IQR / min / max / p95 / mean, plus process-wide peak RSS (Linux `ru_maxrss`, Windows `PeakWorkingSetSize`). Peak RSS is a high-water mark for the whole process, so the commands run each section in its own process.
API pacing: 2.5 s between requests keeps under the server's `state` limit (30/minute); a 429 is waited out (`Retry-After`) and counted, never timed; an endpoint without enough 200s is reported `not_measured` with its status counts, no number.
Not measured by design: a full `baselines tune` (it overwrites the committed `configs/baselines/*.json`). Measure it only in a scratch copy of the repo if you need it.
Honesty rules in code: a section that cannot run is `skipped`/`failed` with the reason; nothing is estimated; credentials never reach the output (tested).

## Evidence (sandbox only; NOT your machine)
Linux, Python 3.13, `twin` section, 20 samples after 3 warm-up: legacy-0 about 3.1 ms/day, physics 1 about 3.6 ms/day. `env`, `episode`, `api` were skipped there (no gymnasium, no running server). These figures prove the script runs, not how fast your machine is. Do not quote them.

## Tests run
Sandbox (small pytest-shim runner, no pytest available): `tests/test_bench_suite.py` 9/9 passed, including the API section against a local stub server (200 timing, a 429 counted and not timed, a 401 endpoint reported `not_measured`, credentials absent from output). `ruff check` and `ruff format` clean. NOT run: `env`, `episode` or `api` against the real stack; anything on your machine.

## Rule for pass 2
Only after you upload the JSON: pick the single hottest path from the numbers (largest median x call count in an evaluation, or the slowest endpoint against its payload size), change only that, re-measure under identical conditions on the same machine, and report relative change with the IQRs. If a change does not move the median beyond the IQR, it is reported as no effect.

## Remaining risks
Machine noise (close other applications, plug in, no battery saver); loopback API times exclude real network; the server runs with its own rate limits and any proxy; the `episode` number includes environment construction, `env` does not.
