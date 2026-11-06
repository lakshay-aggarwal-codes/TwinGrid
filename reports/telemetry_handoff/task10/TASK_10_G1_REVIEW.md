# Task 10 - Compatibility, preservation and G1 review

**Status: Ready for review.** Nothing is implemented and no repository file was changed. Only the owner approves G1.
**Date:** 2026-11-06. **Handoff:** Master Handoff (SHA-256 `bdd37716...d929c0`, matches the Completed Context). **Task 9 ADR:** r4, SHA-256 `47ae669e...ff803be` (matches Task 9 report).

## 0. Recommendation

**G1 can be approved, with conditions.** Tasks 7, 8 and 9 agree on every point I could cross-check, and the Task 9 design fits the repository without touching a frozen path. Three things stop me calling it clean:

1. **The supplied repository is not a valid Phase 3 base.** It holds the Task 5 protocol in `draft` state (no lock file, resolution decimals unset, CK-1 pending), and has no `research/danish_aau/contract/` or `screening/`. The approved/locked versions exist only on the owner's machine. Base commit: **Not established** (archive comment `9b7cad33...`, different from the Task 7 zip's `da2c6155...`).
2. **Tasks 7 and 8 were reviewed from summaries.** `TASK_07_ADR.md` and `TASK_08_CONTRACT.md` were not supplied; I used the Completed Context sections 8 and 8A and the Task 9 ADR's citations. Their hashes could not be checked.
3. **Four shared-file edits are needed before Phase 3/4 can pass CI or stay private** (section 7: G1-D3 to G1-D6). I made none of them.

## 1. G1 checklist

| Item (Master Handoff section 8) | Status | Evidence |
|---|---|---|
| Tasks 7-9 ready for review / approved | Met | Owner approvals 2026-11-05 (7, 8) and 2026-11-06 (9, D-1 to D-8) |
| G-DS = A or B | Met (A) | Accepted 2026-11-05; limits 1-7 in Completed Context section 7 bind later tasks |
| Task 1 baseline understood | Open | Report exists; owner acceptance not recorded; 4 backend + 5 frontend failures (G1-D1) |
| Identity contract | Met, from summary | Task 7 D1-D11 plus amendment 7A |
| Data/provenance contract | Met, from summary | Contract 1.0.0; Task 9 validator probe passed (not re-run here) |
| Storage/serving contract | Met | Task 9 ADR r4 |
| Compatibility plan and frozen paths | Proposed here | Sections 3, 6 |
| Licence/access approach | Met, with gaps | ADR section 11; register entry missing (G1-D3); ignore-file gaps (G1-D4) |

## 2. Cross-check of Tasks 7, 8, 9

| Point | Result |
|---|---|
| Time basis (naive text, no UTC, `ts_utc` null) | Consistent in all three |
| Group power (Ch 1 = Racks 1-3, Ch 2 = Racks 4+6, Ch 3 = Rack 5; never split) | Consistent (7 D7, 8A.3, 9 section 8.5) |
| Tier 1 materialised as `asset`/`sensor` rows (Task 7 D3/D6) vs bundle-only (Task 9) | Reconciled by amendment 7A and owner decision D-2 |
| Provenance `measured` with `origin_db` null, `storage_class = research_import_file` | Consistent; Task 9 probe says the validator accepts it |
| Conflict-missing count | Consistent: the all-channel 10,602 is not used; Task 12 produces the Tier 1 count |
| **N-1 (clarification, no amendment):** `asset_external_id` / `sensor_external_id` in records now name **register entries in the bundle**, not rows in `asset`/`sensor` | Consequence: `/api/assets`, the facility inspector and `maintenance` will never list dataset racks. Task 17 needs the dataset routes, not the inspector's rack list |
| **N-2:** whether contract section 10's five envelopes include a rack list | **Not established** (contract not supplied); Task 16 must check before designing routes |
| Contract 1.0.0 frozen, C-1 to C-5 notes only | Nothing in this review needs a 1.0.0 change |

## 3. Classification

Evidence column cites files read in the supplied snapshot. "Approval" = needs a separate owner decision before anyone edits it.

### Backend, database, ingestion

| Component | Class | Rule for Phase 3/4 |
|---|---|---|
| `src/physics/*`, `src/digital_twin.py`, `src/rl/*`, `models/registry.json`, facility forecaster/anomaly models | **Frozen** | Hashes match Task 1 (section 6) |
| `alembic/versions/*` (15 revisions), `origin` enum/check, `telemetry_sample` constraints | **Frozen** | No migration in v1 (D-1 = bundle). Option C needs approval |
| `models/db_models.py` | **Frozen** (in effect) | Nothing to add; no new table |
| `src/telemetry/ingest.py` (`ingest_samples`), `retention.py`, `scripts/backup.py` | **Reuse unchanged** | Never used for imports. Retention only purges `live` by default; backup counts per stream |
| `src/telemetry/validation.py` (stream grammar), `src/timeutil.py` | **Reuse unchanged** | `import:danish-aau-v5` valid. Reuse only for naming/time checks |
| `api/repositories/facility_repository.py`, `api/services/facility_service.py` | **Reuse unchanged** | One call: create the dataset Facility (`insert_facility`). `insert_sensor` is **not** used (it silently sets `source_tz='UTC'`) |
| `api/routes/facility_routes.py` (`/api/facility`, `/api/assets`) | **Approval required** to change | Exposes the dataset Facility name to demo tokens (F15). Not changed; D-8 precondition applies |
| `api/routes/telemetry_routes.py` | **Reuse unchanged** | Defaults to `stream=live`; cannot reach the bundle; a dataset sensor id answers 404 |
| `api/plugins/maintenance.py` (`/api/maintenance/health`) | **Reuse unchanged** (change = **Approval required**) | Lists every asset and sensor of every facility (lines 185, 187). Safe only because v1 creates no assets or sensors |
| `api/services/live_broadcast_service.py`, `telemetry_window.py`, copilot, anomaly | **Frozen / reuse unchanged** | Live WebSocket and `fac1.*` contract untouched |
| `api/demo_guard.py`, `api/auth.py` (`is_demo_claims`) | **Reuse unchanged** | Task 16 adds its own `require_not_demo`-style dependency in its own file |
| `api/main.py` router list | **Reuse unchanged** | Not needed: `api/plugins/*` is auto-loaded with the general rate limit |
| `api/config.py` rate-limit classes | **Reuse unchanged** | Reuse `telemetry_read`; no `config.py` edit |
| `scripts/seed_facility.py` (36 demo racks) | **Frozen** (tests lock ids and count) | Dataset Facility is created by a new script, after the demo Facility |
| `requirements*.txt` | **Approval required** to change | v1 needs stdlib `sqlite3` only; no new dependency |

### Frontend

| Component | Class | Rule |
|---|---|---|
| `src/features/facility-inspector/*`, `src/three/*`, `components/shell/*` (facility-wide labelling) | **Frozen** until Phase 4 delivers behaviour | Labels and tests intentionally say "facility-wide". Do not edit; build a separate view |
| `src/telemetry/history/*`, `components/charts/*`, `pages/TelemetryHistory.tsx` | **Frozen** (static gate) | The gate bans the word `rack`, `latest`, `stale`, sort, aggregate, reduce, bucket. Dataset code must live elsewhere |
| `src/provenance/*` | **Approval required** to change | `classifyOrigin` returns `unverified` for anything but backend `origin === 'measured'`; dataset records carry `origin_db = null` (R-5) |
| `src/contract/*` (zod layer, fixtures, `capture-contract.mjs`) | **Reuse unchanged** | Gate bans `.default(`, `.catch(`, `z.coerce`. Dataset schemas go in the new feature folder |
| `src/features/registry.ts`, `FeatureRoutes.tsx` | **Reuse unchanged** | `import.meta.glob("./*/index.ts")` auto-registers a new feature folder; no shared edit |
| `src/App.tsx`, `CORE_ROUTE_PATHS` | **Reuse unchanged** | New route comes from the feature module, not `App.tsx` |
| `src/api/*` client | **Extend carefully** | Frontend sends no `facility_id` anywhere; dataset calls must pass it explicitly from their own module |
| New `src/features/dataset-telemetry/` | **Later phase (Task 17)** | Separate from the simulated facility view |

### Tests, CI, docs, deploy

| Component | Class | Rule |
|---|---|---|
| `tests/test_authz_matrix.py` + `tests/authz_matrix.d/*.yaml` | **Extend carefully** | Every route needs a row for all five token types; add a new fragment file |
| `docs/api/openapi.json`, `docs/api/README.md` (CI `gen_api_reference.py --check`) | **Extend carefully** (integrator) | Regenerate after Task 16 |
| `docs/CLAIMS.md`, `claims.json`, README C-10, C-35 | **Frozen** until Phase 4 | Claims change only after tested behaviour (Handoff 4.5) |
| `data/external/REGISTER.json`, `scripts/check_register.py` | **Approval required** | See G1-D3 |
| `.gitignore`, `.dockerignore`, `Dockerfile`, `docker-compose*.yml` | **Approval required** | See G1-D4, G1-D6 |
| `.github/workflows/ci.yml` | **Approval required** | CI never runs `research/danish_aau/tests` (G1-D5) |
| `research/danish_aau/config/*` | **Frozen** | Mapping config must not go here |
| `research/danish_aau/protocol/*` | **Frozen** (locked in the owner's repo) | The supplied copy is a draft; see section 0 |
| `research/danish_aau/evaluation/*` (446 tests) | **Reuse unchanged** | Task 11 reuses its reader if it satisfies the contract |

## 4. Existing tests and gates that prohibit rack attribution today

These are intentional. Phase 3/4 must route around them, not edit them (a loosened gate is an approval item).

| Gate / test | What it locks |
|---|---|
| `src/telemetry/history/sourceGate.test.ts` | No `rack`, `latest`, `stale`, sort, downsample/aggregate, interpolation in the history surface |
| `facility-inspector/FacilityInspector.test.tsx` | `facility-wide-note` says "not specific to this rack"; health score is NOT MEASURED |
| `components/shell/liveSurfaces.test.tsx` | "Facility-wide, live / last known"; "Per-rack telemetry not yet available" |
| `components/shell/IncidentsPanel.test.tsx` | "facility-wide, no sensor attribution" notice |
| `three/readout.test.ts` | Non-live states give no tint on any rack |
| `src/provenance/sourceGate.test.ts` | `'measured'` interpreted in exactly one place; no default to measured |
| `tests/test_task28_rules.py`, `tests/api/test_task28_work_orders.py` | A rack without sensors is `no_data` / NOT MEASURED |
| `tests/test_ig05_rack_id_parity.py`, `tests/test_facility_seed.py` | 36 demo racks, ids, backend/frontend parity |
| `tests/test_authz_matrix.py` | A route without a matrix row fails the suite |
| `tests/test_external_register.py` (2 failing at baseline) | `realData/<name>` referenced in code needs a register entry |

## 5. Risk register

| ID | Risk | Sev. | Mitigation / owner action |
|---|---|---|---|
| R-1 | Phase 3 starts from a snapshot without the locked protocol, screening runner or contract | High | G1-D2: owner supplies or names the base; runs `python -m research.danish_aau.protocol verify` locally |
| R-2 | Tasks 7 and 8 reviewed from summaries | Med | Owner supplies both files or confirms their hashes |
| R-3 | CI does not run `research/danish_aau/tests`; Tasks 11-14 would have no CI | High | G1-D5 |
| R-4 | `check_register.py` fails on any code naming `realData/danish-server-room-v5` (already 2 baseline failures) | High | G1-D3 |
| R-5 | Frontend provenance badge shows "Unverified" for dataset records (`origin_db` null) | Med | G1-D8: separate dataset view model; no edit to `src/provenance/*` |
| R-6 | Docker image copies everything not in `.dockerignore`; only `realData/` and `*.md` are excluded. `research/danish_aau/reports/` and `reports/telemetry_handoff/**` (csv/json/txt) would ship; `.gitignore` ignores `research/danish_aau/reports/` but not `reports/telemetry_handoff/` | High (privacy) | G1-D4 |
| R-7 | Dataset Facility name readable by a demo token via `/api/facility?facility_id=N` (F15) | Med | D-8: private DB only; script refuses when `DEMO_PUBLIC_ENABLED` is truthy; precondition recorded |
| R-8 | Containerised backend cannot see the bundle (compose mounts only `./models`) | Low | Intended containment. G1-D6 confirms dataset routes are local-process only |
| R-9 | Task 15 loads about 54.8 M rows; size and speed are estimates | Med | Task 15 measures before acceptance (ADR section 5, 10) |
| R-10 | Baseline already red: 4 backend, 5 frontend failures; frontend ran on Node 24 (engines want 22.x) | Med | G1-D1; rerun frontend on Node 22.20 before Tasks 17/18 |
| R-11 | Rack identity rests on agent-read image labels | Med | Owner 48-label spot-check before Task 15 (O-2) |
| R-12 | `research/danish_aau/evidence_tools/` was once rewritten by the pre-commit hook | Low | Do not run ruff/pre-commit on that folder; never `git add .` |
| R-13 | Naive label-seconds read as elapsed time | Low | `gap_basis` wording; Task 17 UI text |
| R-14 | Reason-code catalogue still open (8A.7) | Low | Task 12 proposes it; any contract change is a 1.1 amendment |

## 6. Frozen-path comparison with Task 1

Baseline list: `reports/telemetry_handoff/task01/frozen_paths.sha256` (64 lines, 28 source files + 36 `.pyc`). Snapshot compared: the supplied zip.
**Result: 28 of 28 source files identical; 0 differ; 0 missing.** `.pyc` entries skipped (interpreter caches). Covers `src/physics`, `src/digital_twin.py`, `src/rl`, `models/registry.json`, `alembic/versions` (15 files) and `research/danish_aau/config`. Full output: `task10_frozen_path_check.txt`.
Limits: this proves the zip equals the Task 1 baseline for those files, not that HEAD is `d40daafa`. Task 1's list does **not** cover the locked protocol, `tests/`, `docs/CLAIMS.md` or the frontend gates; I checked those by reading only. The zip contains stale `.pyc` for two migrations that have no `.py` (e.g. `..._t9_facility_asset_model copy`); harmless, noted.

## 7. Phase 3 file-ownership plan (proposed; G1 approval makes it binding)

One owner per path. Outputs of data-dependent runs stay under `realData/` (ignored and not shipped in the image). "Integrator" = the lead agent merging reviewed outputs.

| Task | Owns (new paths only) | Must not touch |
|---|---|---|
| 11 Reader | `research/danish_aau/adapter/`, tests `research/danish_aau/tests/adapter/` | `evaluation/*`, `config/*`, `protocol/*` |
| 12 Cleaning | `research/danish_aau/cleaning/`, tests `.../tests/cleaning/`; reason-code catalogue | same; no timezone or UTC logic |
| 13 Mapping | `research/danish_aau/mapping/` (mapping file goes here, **not** `config/`), tests `.../tests/mapping/` | same; no per-rack split of group power |
| 14 Panel | `research/danish_aau/panel/`, tests; L1 file set + manifest under `realData/danish-server-room-v5/l1/` | writes nothing under `reports/` that is tracked |
| 15 Store | `src/dataset_bundle/` (read-only reader, stdlib `sqlite3`), `scripts/build_dataset_bundle.py`, `scripts/create_dataset_facility.py`, tests `tests/test_dataset_bundle*.py`; bundle under `realData/` | `ingest.py`, `telemetry_sample`, `maintenance.py`, `facility_routes.py`, Alembic |
| 16 API | `api/plugins/dataset_telemetry.py`, `api/services/dataset_service.py`, `tests/api/test_dataset_telemetry.py`, `tests/authz_matrix.d/T16.yaml` | `api/main.py`, `telemetry_routes.py`, `/api/state`, WebSocket payload |
| 17 UI | `twin-stream-insight-main/src/features/dataset-telemetry/**` (own client, schemas, mock fixture, tests) | `facility-inspector/`, `three/`, `telemetry/history/`, `components/charts/`, `provenance/`, `contract/`, `App.tsx` |

Shared-file edits (integrator only, each needs an owner decision below): `.gitignore`, `.dockerignore`, `data/external/REGISTER.json`, CI workflow, `docs/api/openapi.json` + `README.md` (regenerate), `docs/CLAIMS.md`.
Order: 11-13 in parallel after G1, then 14, then 15; 16 and 17 after G2. Tasks 11 and 12 need the locked protocol in the base.

## 8. Owner decisions for G1 (recommended answer first)

| # | Decision | Recommendation |
|---|---|---|
| **G1-D1** | Accept Task 1 as the baseline of record (4 backend + 5 frontend failures) | Accept as recorded. The 2 register failures are fixed by G1-D3. Rerun the frontend on Node 22.20.x before Task 17 |
| **G1-D2** | Name the Phase 3 base: supply a zip or commit containing the locked protocol (`protocol_v1.lock.json`), `screening/`, `contract/`, and the Task 7-9 documents; run `protocol verify` locally and report the result | Required before Tasks 11-13 start |
| **G1-D3** | Add a `REGISTER.json` entry for `danish-server-room-v5` | Owner fills source URL, version, retrieved date, licence evidence and terms hash; `redistribution = not_permitted` (your 4 Nov decision). I did not set `license_status` |
| **G1-D4** | Ignore-file additions: `.gitignore` for data-dependent `reports/telemetry_handoff/**` outputs and `.dockerignore` for `research/danish_aau/reports/`, `reports/telemetry_handoff/` | Approve; these two lines of defence currently have gaps (R-6) |
| **G1-D5** | Add a CI step running `pytest research/danish_aau/tests` (synthetic data only) | Approve, or record that those tests are a local-only gate |
| **G1-D6** | Dataset routes work only when the backend runs outside Docker (bundle under `realData/`); no compose change | Accept |
| **G1-D7** | Approve the section 7 placement, including runtime reader in `src/dataset_bundle/` and L1/bundle under `realData/` | Approve |
| **G1-D8** | Task 17 uses its own dataset provenance view model and edits no file under `src/provenance/` | Approve |

If you approve G1, Phase 3 stays locked until G1-D2 is answered. Licence remains local-only; no public exposure, no raw-data commit, no unapproved processor.
