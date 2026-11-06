# Task 7 completion report (Master Handoff section 10 format)

**Task number and title:** Task 7, Identity, site and rack/server architecture

**Status:** Ready for review

**Base commit and branch:**
- The supplied archive `TwinGrid-wip-cp8-hardening.zip` has **no `.git` directory**, so `git rev-parse HEAD`, `git status --short` and the branch could **not** be run. Nothing below is a git verification.
- Three commit identifiers appear in the inputs and they differ: the zip's archive comment is `da2c6155edb870e92d1e1399077717fe5ee0f25d`; the Task 1 report records HEAD `d40daafa60ac589a0a048b4c99be8ff5115138cb` (2026-11-03, parent `b72f0f3`); the Master Handoff expects `b72f0f3`. The zip comment is archive metadata only. Which of them the zip equals is **Not established**. The zip contents are used as the source of truth, as the handoff requires.
- Branch: `wip/cp8-hardening` is implied by the zip file name only.
- `realData/danish-server-room-v5/raw`: absent in the supplied archive (expected, not needed for Task 7).

**Prerequisite check:**
- Task 6 verdict A: accepted by the owner per the Task 7 instruction; `TASK_06_REPORT.md` was read and its "Ready for review" status treated as superseded.
- Inputs supplied: Master Handoff, Tasks 2-5 Completed Context, `TASK_06_REPORT.md`, repository zip.
- **Not supplied:** `TASK_3_REPORT.md` and `task3_identity_register.csv`. Both were marked "if attached" in the instruction, so this is **not a blocker**. Evidence references use the Context section 4 transcription of the same register; the ADR evidence table says so. If the register is supplied later, row ids should be added to the ADR evidence table.
- Raw CSVs: not supplied and not needed.

**Files read:**
- Inputs: the three Markdown inputs above in full.
- Repository: `models/db_models.py` (Facility, Asset, AssetEdge, AssetPose, Sensor, TelemetrySample); `api/services/facility_service.py` (all); `api/repositories/facility_repository.py` (facility, asset listing, `insert_sensor`); `api/routes/facility_routes.py` (route list); `scripts/seed_facility.py` (all); `scripts/demo_seed.py` (layout seeding); `api/config.py` (`telemetry_facility_id` and feature sensor ids); `src/telemetry/ingest.py`, `src/telemetry/validation.py`, `src/telemetry/retention.py` (docstring and stream rules); `docs/adr/005-rack-id-parity.md`; `tests/test_ig05_rack_id_parity.py`; `tests/api/test_routes_facility.py` (the asset_type filter test, grep); `twin-stream-insight-main/src/api/facility.ts`, `src/three/facilityModel.ts` (grep and header); `docs/datasets/danish-server-room-v5/manifest.json` (keys only); `reports/telemetry_handoff/task01/TASK_01_REPORT.md` and `frozen_paths.sha256`; `research/danish_aau/protocol/protocol_v1.toml` and `research/danish_aau/screening/run_task6_screen.py` (hashed only).

**Files created/modified/deleted:**
- Created: `reports/telemetry_handoff/task07/TASK_07_ADR.md`, `reports/telemetry_handoff/task07/TASK_07_REPORT.md`.
- Modified: none. Deleted: none.
- The repository was extracted into a scratch directory outside the deliverable path; the supplied zip itself was not changed.

**Decisions made (within task authority; all are proposals for owner review):**
1. One Facility for the one source-confirmed room; site location, coordinates, timezone stay "Not established"; imported dataset identity is a separate record (`dataset_id = danish-aau-v5`, version in the namespace).
2. All 79 measurement channels plus 6 racks registered as source entities. Tier 1 (6 racks, 37 rack probes, 3 power channels = 40 sensors) is the first materialisation; Tier 2 (11 non-rack probes, 16 air-speed) is optional; the 12 supplementary columns are deferred.
3. IDs built only from the immutable source key (CSV header text, source rack number), with the prefix `danish-aau-v5.`; no row order, DB ids, interpretation, or front/back in an ID.
4. Rack probes attach to rack assets; each power channel to its own power-port asset (existing type `pdu`), never to a rack; non-rack channels to one room-scope `zone`.
5. Many-to-one power attribution through a mapping record (member-rack set, `split_allowed = false`); Rack 5 is the only single-member channel.
6. Mapping time validity is `not_established`; no `asset_edge` or `asset_pose` rows in v1; uniform application over the observation window is recorded as an explicit assumption.
7. Outcome A needs **no change** to validated code or schema. B and C need an owner-approved `server` asset type plus an `installed_in` relation (B) and are documented as contingencies.
8. Unmapped entities stay in the register, counted and listed, with no TwinGrid sensor.

**Evidence and outputs (paths + hashes):**

| Item | SHA-256 |
|---|---|
| `reports/telemetry_handoff/task07/TASK_07_ADR.md` | `8f13794cde8c8be6897c8968548f2bd3eee842b97dc7c4e951daa7edf4ccf458` |
| `TwinGrid-wip-cp8-hardening.zip` (as supplied) | `7db7348d75eb3764b4e7b6c61ced5a3d3e4723e20e9a1a0e777723cbf187a52d` |
| `TASK_06_REPORT.md` | `032efa5ae122251f7f55b0062cabbb0d2420cf4c1b65001391ea2cd76003a6eb` |
| `TwinGrid_Four_Phase_Rack_Server_Telemetry_Master_Handoff.md` | `bdd37716efaf268771380f09876fcb052fdc34ce8ffe5275af4890f0a3d929c0` |
| `TwinGrid_Tasks_2_3_4_5_Completed_Context.md` | `acc40ea90e9da35d661f060e1d9eba1511539920e79a23e9d708b64aa6b0f814` |
| `protocol_v1.toml` in the zip, LF-normalised (recomputed) | `0ff4521697f81c397c81f1af5686284f505956cc239a67b6fe1605adc7b47098` (equals the locked hash) |
| `run_task6_screen.py` in the zip (recomputed) | `684f2fb0ff9e6846bfa727c0a05acc453b757af0b756c36bc9bc95c9fcaeecc7` (equals the Task 6 report) |

(This report's own hash is not listed because it cannot contain itself.)

**Commands executed and exact results:**
- `sha256sum` on the four uploads: hashes above.
- `unzip` of the repository into a scratch directory; `unzip -z` read the archive comment (`da2c6155...`); `ls -a` confirmed no `.git`; `ls realData` reported it absent.
- Read-only `grep`/`sed`/`cat` over the files listed above.
- Python check on the Context table: 48 temperature rows (37 rack_probe, 6 cooling_unit_probe, 5 room_gradient_probe); 48 unique (module, channel) pairs; 16 velocity rows; rack probe split Racks 1, 2, 3, 4, 6 = 1 front + 2 back, Rack 5 = 4 front + 18 back; 9 front + 28 back = 37. All assertions passed in the ADR generator.
- Python hash check of `protocol_v1.toml` and the runner: both equal the recorded hashes (table above).
- Python comparison of `reports/telemetry_handoff/task01/frozen_paths.sha256` (64 entries) with the zip: **28 match, 0 mismatch, 36 absent**; all 36 absent entries are `__pycache__/*.pyc` paths, which are not in the archive. So every listed frozen file that exists in the zip equals its Task 1 hash. This compares against the Task 1 record, not against the commit of the zip.
- No application code, migration, database or test command was run.

**Tests:** passed 0 / failed 0 / skipped 0 / **not run** (design-only task; nothing executable was added or changed). Existing suites were not run. No claim is made about their state.

**Frozen-path check:** No repository file was modified. Frozen paths listed in Master Handoff 4.5 (`src/physics/*`, `src/digital_twin.py`, `src/rl/*`, model registry, Alembic revisions, origin enum, `fac1.*` sensors, facility live payload, the 36 demo racks) were read only where needed (seed and facility code) and are untouched. The Task 1 frozen-hash comparison above found no mismatch.

**Data/licence/privacy limitations:**
- Aggregate and metadata evidence only; no raw or row-level data was used.
- Licence evidence is the owner-recorded CC BY 4.0 (Context section 2). Processing and exposure follow the owner's 4 Nov choice: derived outputs private, no public demo, API or redistribution without a separate owner decision.
- Rack identity rests on agent-read image labels (owner spot-check pending) and on `_mv` images whose extraction from the manifest zips is unconfirmed (ADR O-2, O-12).
- The ADR makes no energy, forecasting or calibrated-physics claim.

**Open blockers and exact owner action:** No blocker. Owner decisions requested (full list with defaults in ADR section 6): O-1 accept or reject uniform application of one undated mapping over the observation window; O-2 finish the 48-label spot-check before Task 15; O-3 `pdu` type and wording for the power measurement port; O-4 Tier 2 materialisation; O-5 no `asset_edge` rows in v1; O-6 Facility name, `frame_note`, and a Phase 3 creation script; O-7 accept `Ch N` = port N and `velocity N` = Port N as corroborated; O-8 location of the dataset record and mapping register; O-9 approve `danish-aau-v5`; O-10 paper's per-server split discrepancy; O-11 name spelling for records; O-12 `_mv` image origin. Optional: supply `TASK_3_REPORT.md` and `task3_identity_register.csv` so evidence rows can cite register ids.

**Findings the owner should know (also in the ADR):**
1. Default facility is the lowest-id facility and the frontend never passes `facility_id`; create the dataset Facility **after** the demo Facility and require an explicit facility on every dataset endpoint.
2. There is no HTTP route to create a facility, asset or sensor; Phase 3 needs a repository-level script.
3. Sensors created through the current functions take `source_tz = 'UTC'` by default, which would silently assert a timezone for undeclared-timezone data (Task 8/9 to resolve).
4. The seed already stores an asset of type `"facility"` that the validator does not allow; the ADR avoids repeating that.

**Dependencies now unlocked (do not start):** Task 8 (parallel group P2-A; it may reference the Task 7 identity vocabulary once reviewed) and, after Tasks 7 and 8 are reviewed, Task 9. Phase 3 stays locked until Task 10 and the owner's G1 approval.
