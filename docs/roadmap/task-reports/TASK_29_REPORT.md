# Task 29 — QA-004 Performance measurement          Status: BLOCKED (measurement); tooling delivered
Base: TwinGrid-main.zip as uploaded. Prerequisite Task 21 is NOT in this tree (`docs/api/` and `src/contract/fixtures/` absent); Task 23 is.
Environment: Python 3.12.3 only. No Docker, Postgres, FastAPI, browser, Playwright or network.

## Summary
The card asks for measured numbers; none could be produced here, so none are recorded. I closed the tooling gaps instead:
the existing scripts did not cover whatif/history/alerts/copilot/access-request percentiles or a ≥ 5,000-sample history, and
nothing seeded real simulator samples. `reports/perf/2026-10/README.md` lists every card item as "not measured".
No optimisation was made, so there is no before/after and no claim to quote.

## Acceptance checklist
- Every claimed improvement has before/after evidence -> met vacuously: no improvement is claimed.
- README quotes only measured numbers -> met: README.md contains no performance figures (checked); `PERFORMANCE_OPTIMIZATION.md` already limits itself to one measured protocol and says retracted claims were removed.
- Measured baseline, budgets, fixes, re-measure -> NOT met (needs the stack).

## Changed files
- CREATE `scripts/perf_endpoints.py` — p50/p95/p99, error rate, payload size per endpoint; 429 counted, never timed.
- CREATE `scripts/perf_seed_history.py` — stores simulator output (`DigitalTwin.step`) through the real `ingest_samples`, back-dated event times, stream `import:perf-2026-10`.
- CREATE `scripts/perf_task29.ps1` — the whole run, raw files into `reports/perf/2026-10/`.
- CREATE `reports/perf/2026-10/README.md` — evidence index, all results "not measured".
- CREATE `tests/test_perf_endpoints.py` — 3 tests (percentiles, 429 handling, no-data case).
- MODIFY `twin-stream-insight-main/docs/frontend/perf/FE-20.md` — status block only.
- CREATE `docs/roadmap/task-reports/TASK_29_REPORT.md`.

## Commands run
- tests/test_perf_endpoints.py via a local pytest stand-in (not real pytest): 3 passed.
- `perf_endpoints.py` against a throwaway local stub HTTP server: confirmed the harness logic (warm-up skipped, 429 excluded from timing and errors, history probe, access-request status header). The stub's latencies are meaningless and were discarded.
- `DigitalTwin.step` loop used by the seeder: 300 steps ran. The database half of the seeder was NOT run.

## Pre-existing failures observed
None observed.

## Not run / blocked
Everything that needs the stack: run `.\scripts\perf_task29.ps1` (Docker Desktop required; it needs `TWINGRID_USERNAME`/`PASSWORD`, `E2E_VIEWER_USERNAME`/`PASSWORD`), then `ruff check .; ruff format --check .; pytest tests/test_perf_endpoints.py -q`.
Not covered by the runner: the 30-minute soak (S1, see FE-20.md), copilot with an LLM, access-request create at load.

## Decisions and defaults used
- Request limits are switched off for latency work (otherwise 429 hides the numbers); the README must record that.
- History data is simulator output with back-dated event times and a fixed daily workload pattern, on its own stream. It is labelled that way, not as live telemetry.
- Existing FE-20.md (in `twin-stream-insight-main/docs/...`) was kept as the frontend procedure; no duplicate file at the repo root.

## Requested cross-task changes
Task 21 first (CI, `docs/api/`, contract fixtures), as the card requires.

## New limitations or risks
The seeder and runner are unrun against the database and Docker; expect small fixes (psql table/column names are assumed from the models, user `postgres`, service `db`).
`perf_endpoints.py` times with keep-alive over loopback when run on the same host as the server; it says so only if you note it in the README.

## Next tasks unblocked
None.
