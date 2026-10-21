# Performance measurement, 2026-10 (Task 29 / QA-004)

**Status: NOT MEASURED.** No number is recorded here yet. The sandbox this task was prepared in had no Docker, Postgres,
backend dependencies, browser or network, so nothing could be run. Raw files appear in this folder when
`scripts\perf_task29.ps1` is run; a number may be quoted anywhere (README, claims) only after it is copied from one of them.

## Environment (fill in after the run; name every line)
| Item | Value |
|---|---|
| Hardware (CPU model, logical CPUs, RAM) | not recorded |
| OS, Python, Node, Docker, Postgres versions | not recorded (`environment_versions.txt`) |
| Client and server on the same machine? | not recorded |
| Request limits (`HTTP_LIMITS_ENABLED`) | runner sets `false`; confirm |
| Data scale | runner stores 5,000 simulator ticks x 5 sensors on stream `import:perf-2026-10` (event times back-dated, workload pattern fixed) |
| Concurrency | 1 and 8 clients (API), 30 + 1 stalled (WebSocket) |

## Coverage of the card
| Card item | Tool | Raw file | Result |
|---|---|---|---|
| API p50/p95/p99 + error rate: state, whatif, history, alerts, copilot (rule-based), access-request create/status | `scripts/perf_endpoints.py` | `api_endpoints_c1.json`, `_c8.json` | not measured |
| WebSocket message and freshness delay | `scripts/ws_load.py ws` | `ws_load_t29.json` | not measured |
| DB timing, history query at >= 5,000 stored samples | `scripts/perf_seed_history.py` + `psql explain analyze` | `seed_history.log`, `db_history_query.txt` | not measured |
| Simulator step cost | `scripts/bench_suite.py --sections twin` | `bench_twin.json` | not measured (an older owner-machine run is in `PERFORMANCE_OPTIMIZATION.md`) |
| Bundle size | `npm run build` | `frontend_build.log` | not measured |
| Page interaction / paint / 3D frame behaviour | `e2e/perf.spec.ts` (`PERF=1`) | `frontend_perf_spec.log`, `twin-stream-insight-main/docs/frontend/perf/results/*.json` | not measured |

Known limits of the tools: access-request create is capped (default 5 requests) so it is not a load figure; copilot is timed
with the rule-based path and the response `mode` is not recorded per request (check it once by hand); the 30-minute soak
(S1) is not part of the runner.

## Budgets, breaches, before/after
Budgets are set only after the table above is filled. No optimisation was made, so there is no before/after.
