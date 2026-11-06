# TwinGrid storage, ingestion and serving architecture (Task 9 ADR)

**Status: Fully approved by the owner on 2026-11-06 (D-1 to D-8), revision 4.** Nothing here is implemented. Revision history: r1 cited Task 8 as a draft; r2 cited it as approved; r3 applied the owner's four changes to D-1 to D-7; r4 records D-8 as approved with a precondition and reorders the findings table.
**Inputs:** Master Handoff (Task 9, sections 4.1-4.3); Tasks 2-7 Completed Context (approved Task 7 decisions D1-D11); `TASK_08_CONTRACT.md` **v1.0.0, approved by the owner on 2026-11-05** (LF-normalised SHA-256 `194869a4f5370bf4da6bebaa75ef45b44aedf072153bc8e5d79314b6ade7d0b7`, as recorded in the Completed Context 2-8; its section 12 names the storage question this ADR answers); `TASK_07_ADR.md` (approved; SHA-256 `8f13794c...f7ccf438`, **file not supplied**, its decisions D1-D11 were taken from the Completed Context); the repository copy `TwinGrid-wip-cp8-hardening__3_.zip` (no `.git`; HEAD **Not established**; read only, nothing executed against a database).

This ADR changes no code, migration, enum, writer, shared API default or frozen path.

## 1. Decision summary

| # | Decision | Section |
|---|---|---|
| S1 | **Imported measured rows are NOT written to `telemetry_sample`.** The existing writer stays the writer of live/replay/simulated rows only. | 4 |
| S2 | System of record for v5 is a **versioned, hashed cleaned-observation file set + ledger + manifest** (Task 12 output). | 3 |
| S3 | Serving store is a **read-only sidecar bundle** (stdlib `sqlite3`, opened `mode=ro`), rebuilt from S2 by a dedicated loader. Same logical schema can later move to PostgreSQL tables. No Alembic change now. | 5 |
| S4 | Time key is the **naive source text plus an integer label key** `t_naive_s`; never UTC, never a `timestamptz`. | 6 |
| S5 | The dataset registry (entities, mappings) lives **in the bundle**; **no `asset`/`sensor` rows are created in v1** (amends Task 7 D6; reason in 2.F8). A `facility` row is still created. | 7 |
| S6 | Derived values live in a **separate store and route family**; none exist for v5, so nothing is built. | 9 |
| S7 | Every dataset request carries explicit `facility_id` and `stream`; **no fallback to `live`**, no default stream. | 8 |
| S8 | Access: bundle absent means 404; authenticated non-demo viewer required; **demo tokens refused**; `access_status` is recorded, never set by code. | 11 |
| S9 | Approving this ADR approves one new bulk **loader for the bundle only**. A bulk writer for `telemetry_sample` is **not** approved. | 10 |

## 2. Repository findings that drive the design (read in the supplied copy)

| ID | Finding | Where |
|---|---|---|
| F1 | `ts_event` is `NOT NULL`, timezone-aware. A stored instant asserts a timezone; the v5 timezone is undeclared. | migration `20261004000000`; `TelemetrySample` |
| F2 | `quality IN ('ok','invalid')`, `invalid_reason IN ('range','future')`, `value NOT NULL`. Contract `flagged`, `missing`, `conflict_unresolved_tie` cannot be stored; a missing cell cannot be a row. | same |
| F3 | `origin IN ('simulated','measured','replay')`; no `derived`/`synthetic`. | same |
| F4 | `ingest_samples` is per-sample: one awaited `INSERT .. ON CONFLICT DO NOTHING .. RETURNING` each (plus a `SELECT` on conflict), max 1,000 per call, first write wins, naive timestamps rejected by default. | `src/telemetry/ingest.py`, `validation.py` |
| F5 | Stream grammar `live` \| `replay:<uuid>` \| `import:<dataset_id>`, 64 chars. `import:danish-aau-v5` is 20 chars and valid (executed). | `validation.py` |
| F6 | Read route defaults `stream=live`, `quality=ok` (hides invalid), keys on `Sensor.external_id` alone (facility not checked), returns UTC `Z`, derives gaps as `> 1.5 x sampling_interval_s`. | `api/routes/telemetry_routes.py` |
| F7 | All other consumers read `stream_id == "live"` only (anomaly window, copilot, maintenance). Retention purges `live` only unless a stream is named. Backup counts per stream. | `telemetry_window.py`, `copilot.py`, `maintenance.py`, `retention.py`, `scripts/backup.py` |
| F8 | **`GET /api/maintenance/health` is not facility-scoped:** it selects every non-retired `Asset` and every non-retired `Sensor`, then runs one query per sensor. Dataset assets and sensors created in the shared tables would appear for every viewer (including a demo viewer) beside the 36 demo racks. Task 7 did not record this. | `api/plugins/maintenance.py` lines ~185-187 |
| F9 | `facility_repository.insert_sensor` has no `source_tz` parameter, so the column default `'UTC'` is applied silently. `'undeclared'` as a `source_tz` fails closed (`TimeContractError`, executed); `'UTC'` does not. | `facility_repository.py`; `src/timeutil.py` |
| F10 | The default facility is the lowest id; the frontend sends no `facility_id`. | `facility_repository.get_facility` |
| F11 | A demo token (`demo=true`, viewer) passes `get_current_user`; `DemoReadOnlyMiddleware` blocks only writes. Any GET route that reads a store is readable by an anonymous demo visitor when `DEMO_PUBLIC_ENABLED` is on. | `api/demo_guard.py`, `api/plugins/demo_session.py` |
| F12 | Runtime deps: `asyncpg`, SQLAlchemy async; `aiosqlite` is dev-only; `pandas` yes, `pyarrow`/`duckdb` no. Production is PostgreSQL; tests use SQLite. | `requirements*.txt`, `docs/architecture/deployment.md` |
| F13 | `realData/` is git-ignored and in `.dockerignore`. `docs/DATA_LICENSES.md` records no verified licence; the AAU dataset is not in `data/external/REGISTER.json`. Owner evidence (CC BY 4.0, screenshot 04-11-2026) lives outside the repo. | `.gitignore`, `.dockerignore`, `docs/DATA_LICENSES.md` |
| F14 | Cadence: Task 4 records 1 s power/temperature with some 2 s steps. The existing gap rule (`1.5 x 1 s`) would flag every 2 s step as a gap. | Task 4 profile; `GAP_FACTOR` |
| F15 | **Facility exposure to demo tokens.** No route lists facilities. But `GET /api/facility?facility_id=N` needs only `get_current_user` (no demo check) and returns `name`, `frame_note`, `created_at` for any integer id, and `GET /api/assets?facility_id=N` returns an empty list for it. A demo token therefore can read the dataset Facility's name and frame note by trying the next integer id. Row-level data is not exposed; the existence and identity of the dataset are. | `api/routes/facility_routes.py`; `api/auth.py` |

## 3. Layers and what lives where

| Layer | Content | Form | Mutability |
|---|---|---|---|
| L0 | Raw CSVs | files, `realData/`, never modified | immutable |
| L1 | Cleaned observations (Tier 1: 37 rack probes + 3 power channels), per-raw-row ledger, dataset record, mapping register, protocol hash | versioned files + manifest with SHA-256s (format: Task 12 decides; deterministic, byte-identical on rerun) | immutable per version |
| L2 | Serving bundle | one read-only SQLite file, rebuilt from L1 | replaced atomically, never edited |
| L3 | Derived series (none for v5) | separate files/tables, see section 9 | n/a |

L1 is the evidence. L2 is a rebuildable index and may be deleted at any time.

## 4. Why not `telemetry_sample` (options considered)

| Option | Verdict | Reason |
|---|---|---|
| A. Insert imported rows into `telemetry_sample` with an assumed zone (UTC or other) | Rejected | Asserts a timezone nobody documented (F1, F9); contradicts Handoff 4.3. |
| B. Same, after the owner approves a timezone | **Deferred, not excluded** | Still hits F2 (no `missing`/`flagged`), F4 (about 54.8 M awaited statements), and F6/F11 (exposure through an existing route). Revisit only with a separate ADR. |
| C. New tables in the main PostgreSQL database | Fallback | Needs an Alembic migration (not allowed in this task). Same logical schema as D; use if the owner wants one database. |
| **D. Read-only sidecar bundle** | **Recommended** | No change to Alembic history, enums, writer or shared defaults; deleting the file removes the dataset; a deployment without the file serves nothing (licence containment by construction); not touched by retention, backup counting or `maintenance`. |
| E. Serve from Parquet | Rejected for v1 | Needs `pyarrow` (new runtime dependency, approval). |

Consequence for Task 8: because `telemetry_sample` is not used, `origin_db` is `null` for imported records, and the contract's `storage_class` for served records is `research_import_file` (the file set is the record; the bundle is an index of it). The contract has no value for "served from a bundle"; see C-1.

## 5. Serving bundle (logical schema, illustrative; Task 15 owns the DDL)

`dataset_version` (one row): `dataset_id` (`danish-aau-v5`), `version`, `doi`, `source_url`, `licence_name`, `attribution_text`, `modifications_statement`, `manifest_sha256`, `protocol_sha256`, `l1_sha256` (hash over the L1 file hashes), `access_status`, `time_basis` (`source_text_undeclared_tz`), `window_first_text`, `window_last_text`, `loaded_at`, per-state row counts.

`entity` (register, one row per channel and rack, including Tier 2 and unmapped): `entity_id`, `kind`, `external_id` (Task 7 grammar), `asset_external_id`, `source_rack_id`, `measurand`, `unit`, `resolution_decimals`, `tier`, `source_file`, `source_column`, `source_label`, `source_position_word`, `mapping_id`, `mapping_version`, `method`, `label_evidence`, `attribution_scope`, `member_source_rack_ids`, `mapping_state`.

`observation` (Tier 1 only): primary key `(entity_id, t_naive_s)`, clustered by that key (SQLite `WITHOUT ROWID`):

| Column | Type | Note |
|---|---|---|
| `t_naive_s` | integer | section 6 |
| `ts_text` | text | the exact source text, kept for the contract's `ts_source_text` |
| `value_ticks` | integer null | value at the protocol resolution as an integer (0.01 degC, 0.1 W); exact, no float rounding; null for `missing` |
| `state` | small int | `observed` / `missing` (flagged is `observed` with `quality`) |
| `quality` | small int null | ok / flagged |
| `reason_code` | text null | e.g. `conflict_unresolved_tie` |
| `disposition` | small int | protocol dispositions that produce a record |
| `group_size` | small int | |
| `first_row_ordinal` | integer | lineage into L0 and the ledger |

`not_reported` is never stored: a second with no row is absent, and the API reports absence (section 8). `exact_duplicate` and `dropped_with_reason` raw rows exist only in the L1 ledger (Task 8 owner answer 2). The ledger is not loaded into the bundle in v1; the API returns the per-record `ledger` summary only.

**Size (engineering estimate, not measured):** 40 series x 1,370,788 unique seconds = **54,831,520 rows** (Task 6 ledger; the 6 period files are 100 % subsets and are **never imported as separate streams**). At an order of 40-60 bytes per row including the key index, about 2-3 GB. Task 15 must measure this before the loader is accepted.

## 6. Time

- `t_naive_s` = `calendar.timegm` of the parsed `YYYY-MM-DD HH:MM:SS` fields: seconds since 1970-01-01 00:00:00 counted on the naive label, **no zone, no DST**. It is an ordering and range key, **not an instant**. Window check (executed): `2024-09-16 16:58:30` to `2024-10-02 13:53:02` is 1,371,272 label-seconds (15.87 days).
- History bounds are `from_source_text` / `to_source_text`, half-open `[from, to)`, parsed with no zone; text containing an offset or `Z` is `bad_request`.
- Durations (gaps, ages) are in label-seconds and say so (`gap_basis = naive_label_seconds`). They equal elapsed time only if the source clock never jumped; that is not established.
- `Sensor.source_tz` is not used (section 7). If the owner later approves a timezone, that is a protocol amendment, then an L1 version bump and a bundle rebuild; stored `t_naive_s` and `ts_text` do not change.

## 7. Facility, asset and sensor rows (amends Task 7 D6, needs the owner's decision D-2)

Task 7 materialised 6 racks, 3 `pdu` assets and 40 sensors in the shared `asset`/`sensor` tables. Finding F8 makes that unsafe today, and F9 makes sensor creation through the existing function assert UTC.

**Recommended v1:** create the dataset **Facility** row only (Task 7 D2 name and `frame_note`), **after** the demo facility (F10), by an owner-run repository script that refuses to run otherwise. Keep assets and sensors as register rows in the bundle with the Task 7 ids unchanged. No `asset`, `sensor`, `asset_edge` or `asset_pose` rows; no `source_tz` question arises. Task 7 ids, `mapping_id`, `mapping_version` and `dataset_id` are carried exactly as the contract requires.

**Alternative (D-2 = materialise):** create Task 7's assets and sensors, but only after (a) `maintenance_health` is facility-scoped under owner approval, and (b) sensors are created by a script that sets `source_tz = 'undeclared'` explicitly (fails closed), never the default. Costs a shared-endpoint change.

### 7A. Amendment to Task 7 D3, D6 and D9 (dated 2026-11-06; owner decision D-2 = bundle-only registry)

Task 7 ADR (SHA-256 `8f13794c...f7ccf438`) is otherwise unchanged. Identifiers, grammar, mapping register contents, tiers and outcomes (A primary, B/C contingencies) are not amended.

- **D3 (entities).** Tier 1 (6 racks, 37 rack probes, 3 power channels) is **registered in the dataset bundle's `entity` table and is not materialised as `asset`/`sensor` rows** in v1. Tier 2 (register only) and Deferred (12 supplementary columns) are unchanged.
- **D6 (attachment).** The attachments are recorded as register relationships with the same meaning: rack probe to its rack (`asset_external_id`, `source_rack_id`); each power channel to its own `pdu` power-port entry, never to a rack; Tier 2 to the room-scope `zone` entry. One entity per channel. No `Asset`, `Sensor`, `AssetEdge` or `AssetPose` row exists. Re-materialisation later (alternative in this section) follows the original D6 with the same ids.
- **D9 (separation).** Separate Facility, separate namespace and no mapping or edges to any demo asset are unchanged. "Needs no change to validated code or schema" still holds and now also holds for the shared `asset`/`sensor` tables, because nothing is written to them. Added: the Facility row is the only shared-table row created, only after the demo Facility, by the owner-run repository script (see F15 and D-8 for where it may be created).
- **Reason (F8, F9):** `maintenance_health` lists every asset and sensor across facilities, and the current sensor-creation function defaults `source_tz` to `UTC`.

## 8. Query semantics

Route paths belong to Task 16; these are the rules every route must meet.

1. **Explicit scope:** `facility_id` and `stream` are required on every dataset request. Missing means 422 `stream_required` (contract error code). `stream` must equal `import:<dataset_id>` of the path's dataset; `live` or any other value is `bad_request`. No default, no fallback, ever.
2. **Existing routes untouched.** `/api/telemetry/sensors/...` keeps `stream=live` and cannot reach the bundle. Because no imported rows enter `telemetry_sample`, the existing route cannot return them; for a dataset sensor id it answers 404 (unknown sensor), which is correct and needs no change.
3. **Envelopes** are exactly the five of contract section 10. A unique `(entity, t_naive_s)` key means keyset paging needs no tie-break column: cursor = last `t_naive_s`. `limit` 1-1000 (contract). The range query is an index range scan limited to `limit + 1`, so its cost does not depend on the span; no span cap is needed.
4. **`latest` and `rack_view` for an imported dataset** mean "as of": optional `as_of_source_text`; omitted means the last record of the dataset window, and the response says `window_status` (see C-3). Wall-clock "now" is never used.
5. **Absence:** history lists stored records only (observed, flagged, missing). A point lookup for a second with no row returns `record = null` with `record_absent_reason = not_reported`; an unregistered entity is `unknown_entity`; a registered Tier 2 channel is `entity_registered_not_loaded` (C-4); a rack's group-power sensors return the group pointer, never a per-rack value. A rack or facility reading is never substituted.
6. **Quality visibility:** `include_invalid` and `include_states` are explicit with default false/`observed`, so missing and flagged records are never silently hidden or silently included; the response echoes both.
7. **Gaps:** do not reuse `1.5 x sampling_interval_s` (F14). A gap is a run of one or more absent label-seconds between consecutive stored records of one entity; each is reported with start, end and length, and the consumer decides significance. Optional in v1; Task 16 decides.
8. **Downsampling for 16-day charts is out of v1.** An aggregate is derived data and must follow section 9; a stride sample can hide spikes. Needs a separate owner decision (D-5).
9. **Historical vs live:** every response is labelled by its `import:` stream and carries the dataset window and `time_basis`; the UI must show "recorded dataset, source time, timezone not established" (Task 17).

## 9. Derived values

No derived rack proxy exists or is planned for v5 (verdict A; group power is measured at group level and is never split). If one is approved later it must: use `provenance = derived`, `storage_class = derived_series`; live in its own tables/file (not `observation`, never `telemetry_sample`); carry `derivation` (formula id and text, inputs, mapping version, code version, approval ref); keep `rack_group` scope when any input is group-scoped; be served only from a separate route family and never from the measured history routes (which must filter on `provenance = measured`). Nothing is built now.

## 10. Ingestion (L1 to L2)

- **Not** via `ingest_samples` (F2-F4). A dedicated loader (Task 15) reads the L1 file set, verifies every L1 hash against the manifest and `protocol_sha256` against the locked protocol, builds the bundle in a temporary file with bounded batches, checks counts and a content digest, then renames it into place atomically. A failed run leaves the previous bundle untouched.
- Idempotent by rebuild: same L1 hash gives the same logical content. The loader reports `inserted / skipped / invalid / conflict`. Because L1 is already canonical, `conflict` and `invalid` must be 0; a duplicate `(entity, t_naive_s)` in L1 is a hard error, never "first wins".
- Verification: per-state counts equal the L1 ledger. Reference counts: raw rows and unique seconds from the Task 6 ledger (full file: 1,371,363 raw rows, 1,370,788 unique seconds); the number of conflict-missing cells **in the Tier 1 subset** (the 37 rack probes and 3 power channels that the bundle loads) is **produced by Task 12** and is the reference for the loader's check. The all-channel total of 10,602 is not used. Per-entity row counts and first/last text are recorded in `dataset_version`.
- Performance target is set by measurement in Task 15 (F4 prevents using the existing writer as a benchmark). SQLite is used for fixtures and the bundle; the PostgreSQL option C is built only if the owner picks it.
- Replaying dataset values through the live pipeline, or labelling them `replay:`/`live`, is not allowed; it would present historical values as current.

## 11. Access and licence enforcement

Owner decision recorded 4 Nov 2026: cloud processing of owner-attached files permitted; **derived outputs stay private**; no public demo, public API or redistribution. Licence is CC BY 4.0 on the Zenodo record (owner screenshot); the repository register still shows no verified licence (F13).

1. **Containment by absence:** the bundle path is configuration; unset or file missing means dataset routes answer 404, identical to an unknown route. The bundle lives under `realData/` (git-ignored, in `.dockerignore`); Task 10 verifies no deploy path copies it.
2. **Authentication:** signed-in non-demo viewer or operator. **Demo tokens are refused** (403 `dataset_not_available_to_demo`) by an explicit dependency using `is_demo_claims` (F11).
3. **`access_status`** in `dataset_version`: `local_only` (default) / `restricted` / `public_approved`. Only `public_approved` could allow demo tokens, and only after the owner records the redistribution decision and licence evidence (`REGISTER.json` entry with terms hash). No code path sets it.
4. **Attribution:** a dataset-record route returns the attribution text and modification statement (CC BY 4.0 requires both); the UI shows them wherever dataset values appear. States the modifications: cleaning, rounding, conflict cells set missing.
5. **Rate limit:** reuse class `telemetry_read` (no `config.py` change). Optional audit of dataset reads uses the existing best-effort audit service.
6. **Facility row (F15, D-8 approved 2026-11-06):** the dataset Facility row is created only in a private/local database. The repository script that creates it **refuses to run when `DEMO_PUBLIC_ENABLED` is truthy**. **Recorded precondition:** before `DEMO_PUBLIC_ENABLED` is turned on against any database that holds the dataset Facility, either (a) remove the Facility, or (b) obtain separate owner approval for the stronger hardening (refusing demo tokens on non-default facilities in `/api/facility` and `/api/assets`). The shared routes are **not changed** by this ADR.
7. **Retention:** none; versions are immutable. Removal is deleting the file and its `dataset_version`. The existing retention job never touches `import:` streams unless named, and `telemetry_sample` holds none.

## 12. Compatibility and approvals

Unchanged: `telemetry_sample`, its constraints, `ingest_samples`, retention, backup, live tick, anomaly window, copilot, maintenance, shared defaults, the 36 demo racks, all frozen simulator/model paths.

Needs separate owner approval (none is granted by this ADR except where stated): (1) any write to `telemetry_sample` from import; (2) Alembic migrations (option C); (3) scoping `maintenance_health` (only if D-2 = materialise); (4) a contract amendment; (5) a new runtime dependency; (6) `access_status = public_approved`. **Granted by approving this ADR:** the bundle loader and read-only reader (S3, S9).

## 13. Risks

| Risk | Mitigation |
|---|---|
| Two storage engines; bundle not in DB backups | Rebuildable from L1; L1 hashes and the loader command recorded; bundle excluded from deployment by design. |
| Multi-instance deployment lacks the file | Out of scope while data is local-only; option C is the documented path when redistribution is approved. |
| Contract 1.0.0 is frozen | Nothing here needs a 1.0.0 change; C-1 to C-5 are optional 1.1 additions (section 14). |
| Label-second durations misread as elapsed time | `gap_basis` label; UI wording. |
| Unmeasured size and speed | Task 15 gate before acceptance. |
| Rack identity rests on agent-read labels (O-2) | Unchanged: owner spot-check before Task 15; entity rows carry `label_evidence`. |

## 14. Contract points (1.0.0 is approved and stays as it is; these are optional additive 1.1 proposals)

- **C-1** `storage_class` for a record served from the bundle: **keep `research_import_file`** (this ADR's reading; no amendment). Adding a member such as `research_import_bundle` would change the validator's storage rule, so it is a 1.1 change only if you want it.
- **C-2** State that history lists stored records only and `not_reported` appears on point lookups.
- **C-3** Add optional `as_of_basis` (`dataset_end` / `requested`) to `latest` and `rack_view`.
- **C-4** Reserve `record_absent_reason` values `not_reported`, `entity_registered_not_loaded`.
- **C-5** Row lineage for grouped rows: `row_ordinal` (approved base: 1-based data row excluding the header; Task 11 confirms against the Task 6 runner) = first row of the group, with `group_size` (Task 12 to confirm).
- **Validator check (2026-11-06, approved Task 8 bundle, stdlib, no database):** a measured v5-shaped observed record with `storage_class = research_import_file` and `origin_db = null` passes `validate_record` (no errors). Controls: `origin_db = 'measured'` with `research_import_file` fails with `E_ORIGIN`; `telemetry_sample` with `origin_db` null fails with `E_ORIGIN`. The probe used a test value, held in memory only, and no data file was written. The contract's pytest suite was not run (pytest is not in the agent sandbox). D-7 stands.
- The optional JSON Schema export left open in contract section 15 is not a Task 9 deliverable; suggested home is Task 16, generated only where a schema library can test it.

## 15. Owner decisions (D-1 to D-8 all approved 2026-11-06; D-1 to D-7 as the defaults in bold, D-8 as proposed)

- **D-1** Storage: **D (sidecar bundle)** / C (PostgreSQL tables, needs migration approval) / B (revisit `telemetry_sample` after a timezone is approved).
- **D-2** Registry: **bundle only; Facility row only** / materialise assets and sensors after `maintenance_health` is scoped.
- **D-3** Approve the bundle loader and reader (S3, S9); `telemetry_sample` bulk writer stays unapproved: **yes**.
- **D-4** Demo tokens refused for dataset routes: **yes**.
- **D-5** Server-side downsampling for charts: **out of v1** / approve as a separately labelled derived view.
- **D-6** Gap definition (section 8.7): **absent-second runs, reported, no threshold**.
- **D-7** Contract points C-1 to C-5: **notes only; 1.0.0 unchanged (final after the validator check in section 14)**.
- **D-8 (approved as proposed)** Facility exposure (F15): **create the dataset Facility row only in a private/local database; the script refuses to run when `DEMO_PUBLIC_ENABLED` is truthy.** Precondition before `DEMO_PUBLIC_ENABLED` is turned on against any database holding the dataset Facility: remove the Facility, or obtain separate approval for the stronger hardening (refuse demo tokens on non-default facilities in `/api/facility` and `/api/assets`). That hardening is a shared-route change, not made here, and needs separate approval.

## 16. What this unlocks

Tasks 7 and 8 are approved, so Task 9 is the last approval G1 waits for. Task 10 (G1) can then classify components using sections 2 and 12. Tasks 15 and 16 build to sections 5, 8, 10, 11; Task 17 follows section 8.9 and the contract. Nothing starts before G1.
