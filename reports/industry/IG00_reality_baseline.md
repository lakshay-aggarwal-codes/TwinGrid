# IG-00 — Reality baseline and documentation truth

Commit under test: `0c5b98aa86bbd307dac3d0d8642ad8977003896e` (`ig00_git.txt`). Working tree at that commit:
` M tests/test_train_anomaly.py` and `?? reports/industry/` (the only entries).
Host paths in the logs show the checkout folder as `DigitalTwin-main`; the attached ZIP is `TwinGrid-main`. I confirmed the ZIP
reproduces one logged defect (F-08, `ScenarioPicker.tsx:44`), but I cannot prove the ZIP equals the checkout (see F-04).

Status words: VERIFIED (code and/or attached output shows it), CONTRADICTED (code and/or output shows it false),
NOT VERIFIED (no evidence attached or readable), NOT RUN (a requested evidence step has no output).

## 1. Evidence received and evidence missing

| Requested evidence | Attached? | Notes |
|---|---|---|
| `ig00_git.txt` | Yes | HEAD + dirty tree above |
| `ig00_pytest.txt` | Yes, **truncated** | Ends mid-run at `tests\test_api_routes_smoke.py` (~18 % of 3769). No summary line. UTF-16 file |
| `ig00_pytest_v.txt` | Yes, **truncated** | Same stop point. 702 outcomes: 611 PASSED, 85 FAILED, 5 ERROR, 1 SKIPPED. Last line: `test_whatif_rejects_unknown_mode PASSED`. No tracebacks (no failure section was reached) |
| `ig00_pytest.xml` (junit) | **No** | NOT RUN as evidence |
| `ig00_alembic.txt` | **No** | NOT RUN as evidence: migration head count is NOT VERIFIED |
| `ig00_frontend_verify.txt` | Yes | `verify` stops at `typecheck` (F-08) |
| `ig00_fe_lint.txt` | Yes | `lint:ci` (`--max-warnings 0`): no output = passed |
| `ig00_fe_test.txt` | Yes | 12 files / 27 tests failed; 1116 passed, 10 skipped (99 files, 1153 tests) |
| `ig00_fe_build.txt` | Yes | Build succeeded (vite 7.3.6, 3087 modules) |
| `ig00_fe_audit.txt` | Yes | 13 vulnerabilities: 5 moderate, 6 high, 2 critical |
| `ig00_compose_build.txt` | **No** | NOT RUN as evidence |
| `ig00_compose_ps.txt` | **No** | Container state NOT VERIFIED except what `db`/`worker` logs and `/readyz` show |
| `ig00_health.txt` | Yes | `/healthz` ok; `/readyz` ready, `degraded: {optimizer}` |
| `ig00_db_logs.txt`, `ig00_worker_logs.txt` | Yes | See F-17, F-18 |
| API and Redis container logs | No | NOT VERIFIED |

Nothing below says "passes" for anything not in an attached output.

## 2. The eight items you asked me to resolve

**(a) README replaces three documents that still exist: CONTRADICTED.** `README.md:9-10` says it replaces `README.md`, `ARCHITECTURE.md`,
`FINAL_REVIEW.md`, `DOCUMENTATION_SUMMARY.md`. The three others are in the tree (also listed in `TWINGRID_REPOSITORY_MAP.md`). They describe a build the README itself
disowns (e.g. real Electricity Maps data; `src/digital_twin_documented.py`, which does not exist; `data/cleaned/` holds only `README.md`). Minimal edit applied to the README sentence.
Merging, archiving or deleting the three files is IG-17 (F-19).

**(b) STATUS.md says FE-17 must be "confirmed applied": VERIFIED applied, now recorded.** `src/pages/Evaluation.tsx` exists; the build emits `dist/assets/Evaluation-BNB41q1l.js`
(`ig00_fe_build.txt`); `src/evaluation/schema.test.ts` ran (`ig00_fe_test.txt`); `git status --short` lists no frontend change, so it is committed at `0c5b98a`.
FE-18 is likewise present (`TelemetryHistory-P371R0nj.js` built; its tests ran). STATUS.md rows edited accordingly. A real-backend capture of `/api/evaluations` is NOT RECORDED.

**(c) G-EVAL.md says the gate is not open while `evaluation_routes.py` exists: CONTRADICTED.** `api/routes/evaluation_routes.py` defines `GET /api/evaluations` and
`GET /api/evaluations/{evaluation_id}`; `api/main.py:123` includes the router. The sentences "there is no evaluation endpoint" (G-EVAL.md:3, and the "None." table row)
are false and are corrected. The gate itself stays unsigned: no real-stack capture exists (F-20). Only one evaluation report exists, `baselines_only_0fcafef9d28fd539`,
outcome `NOT_EVALUATED`, no PPO row, `physics_version: legacy-0 (implicit)`.

**(d) `RECONSTRUCTED` markers in `src/versions.py`: VERIFIED present; correctness NOT VERIFIED.** Lines 32-33 (`PHYSICS_V2`, `KNOWN_PHYSICS_VERSIONS`) and 145-170+
(`physics_identity`, `assert_same_physics_identity`) carry the marker, meaning the text was rebuilt rather than recovered. `tests/test_physics_v2.py` exists but was not reached
by the truncated pytest run. The marker must not be removed until that test file and the golden tests run green (F-14). `tests/golden/*` passed in the log (6 + 5 tests).

**(e) Dockerfile base image digest never resolved: VERIFIED.** `Dockerfile:4-8` states the digest "could not be resolved"; `ARG PYTHON_IMAGE=python:3.12.10-slim` is unpinned. Owner IG-01 (F-07).

**(f) Registry waivers and PPO candidates: VERIFIED.** `models/registry.json`: `forecaster` (`:51`) and `anomaly_detector` (`:152`) are `promoted` with
`compat_waiver` `legacy-0-physics-until-T26`, `expires_after_task: "T26"`. T26 work exists in code (`src/anomaly_detector.py:131,323`) but neither waiver is retired.
`ppo_optimizer` `20260927T143232Z` is `quarantined`; five artifacts `ppo-p1-e2-cd2345024` s0-s4 are `candidate` (physics `1`). The only evaluation is baselines-only `NOT_EVALUATED`.
`/readyz` reports `optimizer=not_loaded` / `degraded: {optimizer}`, consistent with no promoted PPO. Owners IG-14 (waivers), IG-15 (PPO).

**(g) `FloorHeatmap.tsx` still present: VERIFIED.** 179 lines. Three `analyticsGate.test.ts` tests fail in `ig00_fe_test.txt` (`expected [ './FloorHeatmap.tsx' ] to deeply equal []`).
By grep, the only other mention in `src/` is a comment at `src/three/visualizationModes.ts:27`; no import found. Owner IG-02 (F-10).

**(h) SECURITY.md stale about CI dependency scanning: CONTRADICTED.** `.github/workflows/ci.yml:217-234` (job `audit`: `pip-audit --requirement requirements.lock --require-hashes --strict`)
and `:272` (`npm audit --audit-level=high`). Sentence corrected. Whether those jobs pass in CI: NOT VERIFIED (no CI log). Locally, `npm audit` fails the CI threshold (F-11).

## 3. Claim ledger by document

Scope note: `DOCUMENTATION_SUMMARY.md` (609 lines) and the two repository maps describe documentation and a build that the README disowns; I checked them at section level
against the tree, not sentence by sentence. Every claim in them is NOT VERIFIED unless listed. IG-17 owns them. The other documents were checked claim by claim for the claims below.

### README.md
| Claim | Verdict | Evidence |
|---|---|---|
| Replaces 3 other docs (`:9-10`) | CONTRADICTED | (a) |
| `src/digital_twin_documented.py` / `data/cleaned/carbon_intensity.csv` don't exist | VERIFIED | `ls`; `data/cleaned/` has only `README.md` |
| Flat 475 gCO2/kWh fallback | VERIFIED | `src/carbon_provider.py` docstring (`is_fallback`, `constant_assumption`) |
| Migrations "5 revisions, chain intact, never run on a live Postgres" | NOT VERIFIED | alembic output not attached; `tests/test_alembic_chain.py` has 1 failure (F-03) |
| "`docker compose up` (`db`, `redis`, `worker`, `backend`)" | VERIFIED as configured | `docker-compose.yml:2,32,47,78` define `db`, `redis`, `worker`, `backend` (plus profile-gated `debug-db`, `mqtt-ingest`, `backup`). Running state NOT VERIFIED (no `compose ps`) |
| "Never deployed to an actual platform" | NOT VERIFIED | not testable from evidence |
| `pytest tests/ -q` "needs to actually be run and confirmed green" | VERIFIED as an open item | it is not green: F-01, F-02 |
| Frontend "not covered by this document" | VERIFIED (and a gap) | IG-17 |

### SECURITY.md
| Claim | Verdict | Evidence |
|---|---|---|
| JWT HS256; `JWT_SECRET_KEY` required | VERIFIED | `api/auth.py:68,145`; `api/startup_checks.py` |
| Rate limits login 10/min, register 5/hour | VERIFIED | `api/auth.py:406` (`/register`, `5/hour`), `:461` (`/login`, `10/minute`) |
| `/api/optimize` 10/min | VERIFIED | `api/config.py:128` |
| CORS explicit list | VERIFIED | `api/startup_checks.py` (`CORS_ALLOWED_ORIGINS`, wildcard flagged) |
| `/metrics` and `/healthz` unauthenticated | `/metrics` CONTRADICTED, `/healthz` VERIFIED | `api/routes/metrics_routes.py:34-50` (bearer required when `METRICS_TOKEN` set; closed in production without it; open only in dev/test with none) |
| No CI dependency scanning | CONTRADICTED | (h) |
| "student/portfolio project" framing | VERIFIED text; left for IG-08 | |

### ARCHITECTURE.md, FINAL_REVIEW.md
| Claim | Verdict | Evidence |
|---|---|---|
| Diagram: Electricity Maps, WRI Aqueduct, SPECpower, ASHRAE as real inputs via `data/cleaned/` | CONTRADICTED | `data/cleaned/` empty except README; README fallback text |
| "In-process, not Redis pub/sub" real-time design | NOT VERIFIED | Redis present in compose; `/readyz` `redis=ok`; broadcast code not read |
| Railway/Nixpacks production; Dockerfile for local only | NOT VERIFIED | `nixpacks.toml`, `Procfile` exist; README says never deployed |
| FINAL_REVIEW "No CI dependency scanning" row | CONTRADICTED | (h); corrected |
| FINAL_REVIEW "4 of 7 fully verified" DoD table; "20 phases complete" | NOT VERIFIED | no attached evidence; test status contradicts any "tests pass" implication (F-01, F-02) |
| FINAL_REVIEW `WhatIfTab` `Math.random()` P0 | NOT VERIFIED | not checked in IG-00 scope; IG-17/IG-18 re-check |

### ML_DOCUMENTATION.md
| Claim | Verdict | Evidence |
|---|---|---|
| Carbon term "real diurnal Electricity-Maps-derived intensity" | CONTRADICTED | `src/carbon_provider.py`; no cleaned CSV. Corrected |
| Anomaly threshold 95th percentile; PPO obs 9 dims; RUL cap 125; C-MAPSS proxy | NOT VERIFIED | model code and tests not run (pytest truncated) |
| Forecaster baseline "not established" | VERIFIED as stated | IG-14 owns closing it |

### docs/OPERATIONS.md
| Claim | Verdict | Evidence |
|---|---|---|
| "no restore drill has been recorded" | VERIFIED | `reports/ops/` does not exist |
| `scripts/backup.py`, `restore_verify.py` exist; `backup` compose profile | VERIFIED | `docker-compose.yml:142-148` |
| Compose requires `JWT_SECRET_KEY`, `MQTT_BROKER`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD` | PARTLY VERIFIED | `REDIS_PASSWORD` `:?` at `docker-compose.yml:38-40`; others not re-read |
| `METRICS_TOKEN` mandatory in production | VERIFIED | `api/routes/metrics_routes.py:34-50` |

### twin-stream-insight-main/docs/frontend/STATUS.md
| Claim | Verdict | Evidence |
|---|---|---|
| FE-17, FE-18 applied | VERIFIED | (b) |
| FE-16 G-RUN passed at `db92487705ba6ffe554b4c819b8006187966a446` | NOT VERIFIED | owner record not attached |
| FE-19 not signed; FE-20 not measured | VERIFIED | no run output attached |
| Open item 3: `FloorHeatmap.tsx` exists, test should fail | VERIFIED | (g) |
| Open item 4: `.pulse-dot`, `.scan-line` unguarded, unused | VERIFIED | `src/index.css:101,116-128`, no `@media (prefers-reduced-motion)` around them; no `.tsx` uses them |
| Open items 5-8 | VERIFIED as open | no counter-evidence |

### twin-stream-insight-main/docs/frontend/RISKS.md
| Claim | Verdict | Evidence |
|---|---|---|
| R-1 token in WebSocket URL | NOT VERIFIED | `wsTransport.ts` not read in IG-00; IG-09 owns |
| R-4 no error receiver | VERIFIED | no `client-errors` route in `api/` |
| R-5 vitest advisory "moderate" | INCOMPLETE | audit also lists `tinypool` critical (RCE) and others. Corrected |
| R-3 bundle test asserts no demo credentials | **CONTRADICTED by a failing test** | `bundleScan.test.ts` fails twice (F-09) |

### twin-stream-insight-main/RELEASE.md
| Claim | Verdict | Evidence |
|---|---|---|
| `lint:ci` is `--max-warnings 7`, 7 accepted warnings | CONTRADICTED | `package.json:18` is `--max-warnings 0`; `ig00_fe_lint.txt` passes with no output. Corrected |
| `npm audit`: 2 moderate, 0 high/critical | CONTRADICTED | `ig00_fe_audit.txt`: 13 (5 moderate, 6 high, 2 critical). Corrected |
| Build refuses production if `VITE_DEMO_USERNAME`/`PASSWORD` unset | CONTRADICTED | `vite.config.ts:10,30-32` only requires the API URL and *warns* demo vars are ignored. Corrected |
| Build warns on unset `VITE_ERROR_REPORT_URL` | VERIFIED | `ig00_fe_build.txt` |
| "VITE_DEMO_PASSWORD is public. Vite inlines it" | NOT VERIFIED | conflicts with `vite.config.ts:30-32`; see F-09 |

### docs/frontend/contracts/G-*.md
| Doc | Verdict |
|---|---|
| `G-EVAL.md` "no endpoint, gate not open" | CONTRADICTED (c). Corrected. Capture files `G-EVAL.capture-*.json` VERIFIED present |
| `G-HIST.md` "captured in a sandbox, not on the real stack"; "simulator writes no stored telemetry" | NOT VERIFIED on a real stack. IG-04 owns the producer. Note `/readyz` `broadcast=ok` only |
| `G-RUN.md`, `G-SCN.md`, `G-SCN.real-run.md` | Captures present (VERIFIED as files); "passed on real backend" NOT VERIFIED here |

## 4. Findings

Severity: P0 = blocks everything downstream; P1 = serious and gating; P2 = must fix before industry-grade; P3 = hygiene.

| # | Sev | Finding | Evidence | Owner |
|---|---|---|---|---|
| F-01 | P0 | Backend test run ends at ~18 %: both runs stop after `test_api_routes_smoke.py::test_whatif_rejects_unknown_mode`; the next test in file order is `test_benchmark_classifies_current_pue`. About 3,067 of 3,769 collected tests have no result and there is no summary line. Cause not diagnosed (hang, crash or killed session are all possible) | `ig00_pytest.txt`, `ig00_pytest_v.txt` | IG-01 |
| F-02 | P0 | 85 FAILED + 5 ERROR of 702 reported outcomes. By file: audit_events 13, error_contract 14, http_limits 6, live_tick_store 6 (5 ERROR), provenance_writers 5, characterization (determinism 3, **golden_physics 4**, route_contracts 5, t3_anomaly_pipeline 10, t3_routes_repo_migration 7, ws_and_manager 4, ws_payload_provenance 2), plus single failures in physics_v1_api, routes_alerts_webhooks (2), auth_refresh, health_metrics (2), state_whatif (2), state_preview_isolation, websocket, alembic_chain. No tracebacks, so causes unknown. Golden physics and determinism failures are an invariant risk (rule 4/6) | `ig00_pytest_v.txt` | IG-01 |
| F-03 | P1 | `tests/test_alembic_chain.py` has one failure and `audit_alembic_graph.py` output is missing: the one-head invariant is NOT VERIFIED | `ig00_pytest_v.txt`; no alembic file | IG-01 |
| F-04 | P1 | Dirty working tree: `tests/test_train_anomaly.py` is modified at the evidence commit. It may differ from the ZIP, so every backend test result is for "HEAD + that edit" | `ig00_git.txt` | IG-01 |
| F-05 | P1 | Compose build and `compose ps` output missing, so image build and API/Redis container health are NOT VERIFIED. What is shown: `db` and `worker` ran; `/healthz` ok; `/readyz` ready with `database/schema/broadcast = ok`, `redis=ok`, `anomaly_detector=ok`, `optimizer=not_loaded` | `ig00_health.txt`, logs | IG-01 |
| F-06 | P3 | `worker` start logs: click `UserWarning` "`--serializer`/`-S` used more than once" under rq 1.16.2. Worker started and listened on `twingrid` | `ig00_worker_logs.txt` | IG-01 |
| F-07 | P1 | Dockerfile base image not pinned by digest | `Dockerfile:4-8` | IG-01 |
| F-08 | P1 | `npm run verify` fails at typecheck: `ScenarioPicker.tsx(44,87)` and `(44,116)` TS2339 `raw` on `KindSupport` (`src/scenarios/model.ts:25`; reproduces in the ZIP at line 44). `lint:ci`, `test`, `build` were therefore only run individually. IG-02's list does not name this defect: amendment needed | `ig00_frontend_verify.txt` | IG-02 |
| F-09 | P1 | Production bundle scan fails twice: bundle contains the demo-username sentinel and a `VITE_DEMO_(USERNAME\|PASSWORD)` pattern, although `vite.config.ts:30-32` says demo sign-in is not in production bundles. Either a possible credential/hint leak or a test-environment cause: NOT DIAGNOSED | `ig00_fe_test.txt` (`bundleScan.test.ts`) | IG-02 (IG-09 reviews result) |
| F-10 | P2 | `FloorHeatmap.tsx` present; 3 gate tests fail | (g) | IG-02 |
| F-11 | P1 | `npm audit`: 2 critical (`tinypool`, RCE prototype pollution), 6 high (`braces`, `source-map-js` and dependents), 5 moderate. CI runs `npm audit --audit-level=high`, so the CI `frontend` job would fail. Fixes involve dependency changes (`vitest` 5 major, `tailwindcss` major via `--force`; `source-map-js` is a non-breaking `npm audit fix`). **IG-02 and IG-08 both forbid dependency/lock changes, so no task can fix this as written: owner decision needed (see section 6)** | `ig00_fe_audit.txt` | IG-02 (needs amended Allowed files) |
| F-12 | P1 | 27 frontend tests failing in 12 files (see F-09, F-10 for 5). Others: `alerts`, `esgReport`, `facility` test files fail to load ("error when mocking a module" / `ReferenceError`); `authClient` (2), `RunMonitor` (4), `sessionEnd` (1), `OperationsConsole` (5, text mismatch e.g. `score 0.0123 / threshold 0.0100`), `evaluation/schema` (2), `useWhatIf` (5), `useFeed` (4, "useFeed must be used inside <SimulationProvider>"); 24 "Uncaught Error"/"Super expression must either be null or a function" lines from `react-dom` suggest a shared setup or dependency cause. Not diagnosed | `ig00_fe_test.txt` | IG-02 |
| F-13 | P2 | IG-02 says "keep `lint:ci` at the current 7-warning cap". The actual cap is 0 (`package.json:18`) and it passes. Keep 0 | `package.json`, `ig00_fe_lint.txt` | IG-02 |
| F-14 | P2 | `src/versions.py` `RECONSTRUCTED` markers (d); `tests/test_physics_v2.py` not reached | (d) | IG-01 |
| F-15 | P3 | Build warns two chunks > 500 kB: `index` 748 kB (gzip 240 kB), `three` 806 kB (gzip 218 kB); `VITE_ERROR_REPORT_URL` unset | `ig00_fe_build.txt` | IG-07 (size), IG-10 (receiver, R-4) |
| F-16 | P2 | `index.css` `.pulse-dot`, `.scan-line` have no reduced-motion guard and no users | STATUS item 4 verified | IG-02 |
| F-17 | P3 | Postgres restarted 2026-10-11 04:11 after an unclean stop ("not properly shut down; automatic recovery"). Recovery completed. Relevant to any durability claim | `ig00_db_logs.txt` | IG-12 |
| F-18 | P3 | `/readyz` `degraded: {optimizer}`; PPO not promoted (consistent with F-21) | `ig00_health.txt` | IG-15 |
| F-19 | P2 | `ARCHITECTURE.md`, `FINAL_REVIEW.md`, `DOCUMENTATION_SUMMARY.md`, repo maps describe another build (a) | README; tree | IG-17 |
| F-20 | P2 | G-EVAL gate unsigned: no real-stack capture of `/api/evaluations`; only a baselines-only `NOT_EVALUATED` report exists | (c) | IG-03 (capture), IG-15 (decision) |
| F-21 | P1 | PPO: 5 candidates (s0-s4) + 1 quarantined; no PPO evaluation; waivers on 2 promoted models expired after T26 | (f) | IG-15 (PPO), IG-14 (waivers) |
| F-22 | P2 | Carbon is a flat 475 gCO2/kWh assumption; no cleaned data | README, `src/carbon_provider.py` | IG-13 |
| F-23 | P2 | `SECURITY.md` still framed as student/portfolio project; no disclosure contact; no Dependabot | `SECURITY.md` | IG-08 |
| F-24 | P2 | No restore drill recorded | `reports/ops/` absent | IG-12 |
| F-25 | P2 | No `/api/client-errors` receiver (R-4) | `api/` grep | IG-10 |
| F-26 | P2 | Stored telemetry producer not verified on a real stack (G-HIST) | G-HIST.md | IG-04 |

Every finding has an owner. F-08 and F-11 need the owners' Allowed lists amended (section 6).

## 5. Documentation corrections made (minimal, factual only)

`README.md` (supersession sentence), `SECURITY.md` (`/metrics` auth, CI scanning), `FINAL_REVIEW.md` (CI-scanning row), `ML_DOCUMENTATION.md` (carbon term),
`docs/frontend/contracts/G-EVAL.md` (endpoint exists; gate unsigned), `twin-stream-insight-main/RELEASE.md` (lint cap, audit counts, demo-var build rule),
`twin-stream-insight-main/docs/frontend/STATUS.md` (FE-17/FE-18 applied, stale "confirm" note), `twin-stream-insight-main/docs/frontend/RISKS.md` (R-5 completeness).
No code, tests, configs, workflows, models or data were changed.

## 6. Decisions and evidence needed before IG-01 and IG-02

1. **IG-01 evidence:** a pytest run that completes. Run `pytest -q -x --tb=short -p no:cacheprovider tests\test_api_routes_smoke.py::test_benchmark_classifies_current_pue` first to see the stopping point, then the full suite per directory with `--tb=short`, saving full output.
2. `reports\industry\ig00_alembic.txt`, `ig00_compose_build.txt`, `ig00_compose_ps.txt`, and `ig00_pytest.xml`.
3. `git diff tests/test_train_anomaly.py`, and either commit it or confirm the ZIP includes it.
4. **Owner decision (F-11):** allow IG-02 to change `package.json` and `package-lock.json` for security patches, or record a written waiver for the critical/high findings. Until then IG-02's `npm audit --audit-level=high` check cannot pass.
5. **Owner decision (F-08):** add the `ScenarioPicker.tsx` type error to IG-02's task list.
