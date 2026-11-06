# ADR (Task 7): Identity, site and rack/server architecture for the imported Danish AAU v5 dataset

| Field | Value |
|---|---|
| Status | **Proposed. Ready for owner review.** Not accepted, not approved. Only the owner approves. |
| Task | Task 7, "Identity, site and rack/server architecture" (Master Handoff section 5/6), parallel group P2-A |
| Prerequisite | Task 6 = verdict A (rack-capable). Accepted by the owner per the Task 7 instruction; the "Ready for review" status in `TASK_06_REPORT.md` is treated as superseded. |
| Nature | **Design only.** No code, migration, schema, asset-validation change or new asset was made. |
| Prepared | 5 November 2026 |
| Dataset | Danish AAU Server-Room, version v5, DOI 10.5281/zenodo.21262042, CC BY 4.0 (Melgaard, Juul, Nielsen, Jensen; Aalborg University) |
| Repository | `TwinGrid-wip-cp8-hardening.zip` (no `.git` inside; see report for what could and could not be recorded) |

---

## 1. Context

### 1.1 What the source supports (accepted evidence)

From the Task 3 audit as recorded in `TwinGrid_Tasks_2_3_4_5_Completed_Context.md` section 4, and the accepted Task 6 verdict:

- **One physical room** labelled "Serverroom" with an air cavity above. City and building are **not stated**; no second site found. Physical site location: **Not established**.
- **Six racks**, numbered 1 to 6 (workbook `AAU-layout-file.xlsx`, sheet `Ark1`, column `Rack`; probe images).
- **48 temperature channels** in the 1 s power/temperature CSVs (`Temperature mod M ch C`): **37 rack-labelled probes** (Racks 1, 2, 3, 4, 6: 1 "front" + 2 "back" each = 15; Rack 5: 4 "front" + 18 "back" = 22), plus **11 non-rack probes** (6 cooling-unit, 5 room-gradient).
- **3 power channels** (`Power Ch 1/2/3 (W)`), each a **rack-group** measurement: workbook column K "Power use measurement port" (port 1: Racks 1, 2, 3; port 2: Racks 4 and 6; port 3: Rack 5); `power.png` legend "Rack 1-3", "Rack 4+6", "Rack 5". Only Rack 5 has a channel of its own.
- **16 air-speed channels** (`velocity 1..16`, "Port N" on the velocity images): cooling-unit/room points, **no rack attribution**.
- **Two supplementary files** (surrounding temperatures, 6 columns, 900 s; ventilation, 6 columns, 120-780 s): room/facility level; units of both unknown.
- **No server-level measurement and no server-to-rack map.** Servers exist only as workbook inventory notes (several rows "Unknown server/PC" or "?").
- Period files are 100 % subsets of the full file (Task 6, frac_rows_identical 1.000000 for all six), so they are **not** independent replications.

### 1.2 What is not established (and this ADR must not paper over)

- Front = inlet / back = outlet. "front" and "back" are the source's words only.
- `Power Ch N` = workbook port N, and `velocity N` = "Port N": not stated in words. Task 4 value ranges match the plotted series, so the link is *corroborated*, not *documented*.
- CAD layers `Cabinet 1`..`Cabinet 6` equal Racks 1-6 (never stated; rack identity comes from image labels).
- CAD handle-to-channel links (none exist; coordinates have no stated unit).
- **Whether the layout held during the 2024 run** (16 Sep 2024 16:58:30 to 2 Oct 2024 13:53:02, naive text).
- The timestamp timezone (`undeclared`).
- Image labels were read by an agent by eye (48 labels cross-checked, 48 unique module/channel pairs); an owner spot-check is still advised.
- The `Measurement_visualization` images sit in `_mv/`, a folder that is not in the manifest and whose extraction from the manifest zips is unconfirmed (Task 2 note).
- **Open discrepancy:** the paper says power was recorded per rack by PDUs and split evenly per server; the dataset has 3 channels for 6 racks. Unresolved. No channel is ever split across racks.

### 1.3 What the repository actually does (verified by reading the supplied zip, not by running it)

Detail and line references are in Appendix C. The facts that drive this design:

1. `Facility` = name (unique) + `frame_unit` (CHECK = 'm') + `frame_note`. It has **no** place for dataset name, version, DOI or licence.
2. `Asset` is unique on `(facility_id, external_id)`. `asset_type` is validated TEXT against `ASSET_TYPES = {zone, rack, crac, chiller, cooling_tower, pdu, ups}`. **There is no `server` type** and no `room`/`facility` type in the validator.
3. `RELATIONS = {located_in, serves, powered_by}`; an edge reads "child relation parent"; `located_in` parent must be a `zone`; `powered_by` parent must be `pdu`/`ups`. Edge and pose `valid_from` are **NOT NULL**; the service defaults an omitted `valid_from` to *now* and refuses a future one.
4. `Sensor.external_id` is **globally** unique (not per facility), 128 chars; a sensor must have an `asset_id`; there is no probe-position or label column; `source_tz` is NOT NULL with default `"UTC"`; the repository `insert_sensor` has no `source_tz` parameter, so it would silently take `"UTC"`.
5. `TelemetrySample` origin CHECK is `simulated | measured | replay`; stream ids are `live | replay:<uuid> | import:<dataset_id>` (<= 64 chars; dataset id `[A-Za-z0-9._-]+`); unique on `(sensor_id, stream_id, ts_event)`. Retention never touches `import:` streams unless named.
6. The **36 demo racks** are `zone-<n>-row-<n>-rack-<n>` assets of the facility named "Default Facility", seeded by `scripts/seed_facility.py`; there are **no per-rack sensors**; five facility-level sensors `fac<facility_id>.<measurand>` hang on a `facility-level` asset whose type `"facility"` is written through the repository and is **outside** `ASSET_TYPES`.
7. `GET /api/facility` and `GET /api/assets` serve the **lowest-id facility** when `facility_id` is omitted, and the frontend omits it. `TELEMETRY_FACILITY_ID` defaults to 1 and builds `fac1.*`.
8. There is **no HTTP route** to create a facility, asset or sensor. Only the repository/service functions and scripts can.

---

## 2. Decision summary

| # | Decision |
|---|---|
| D1 | The imported dataset has its own identity: `dataset_id = danish-aau-v5`. It is carried by a versioned **dataset record** (fields in 3.1) and by a namespace prefix on every imported ID. It is not stored in `Facility`. |
| D2 | **One Facility** for the one source-confirmed site (the Serverroom). Physical location, coordinates, orientation, timezone: **Not established**, stated as such in the facility's `frame_note`. No poses are ever recorded for imported assets. |
| D3 | All **79 measurement channels** and all 6 racks are registered as source entities with a class and an evidence status. **Tier 1** (materialised as TwinGrid rows in the first implementation): 6 racks, 37 rack probes, 3 power channels. **Tier 2** (identity defined now, materialisation optional, owner decision O-4): 11 non-rack probes and 16 air-speed channels. **Deferred**: the 12 supplementary columns. |
| D4 | IDs are **deterministic strings built only from the immutable source key** (CSV header text, source rack number). Row order, file order, DB integer ids, interpretation (rack number of a probe, front/back, class) are never in an ID. |
| D5 | Interpretation lives in the **mapping register**, not in IDs. Source words ("front", "back", "Rack 1-3", "Cooling wall Front L") are kept verbatim as attributes. |
| D6 | Attachment: rack probes attach to the **rack asset**; each power channel attaches to its own **power-port asset** (existing type `pdu`), never to a rack; Tier 2 channels attach to one room-scope `zone` asset. A channel is **one sensor regardless of how many CSV files contain it** (file is lineage, not identity). |
| D7 | Many-to-one power attribution is a **mapping record with a member-rack set and `split_allowed = false`**. No per-rack power field exists for a group channel. |
| D8 | Time validity of every mapping is **`not_established`** in v1. No `asset_edge`/`asset_pose` rows are created for imported assets in the first implementation (reasons in 3.6). Applying one mapping uniformly over the observation window is an explicit, recorded **assumption** (owner decision O-1). |
| D9 | Imported assets are **fully separate** from the 36 demo racks: separate Facility, separate namespace, no mapping, no edges. Collision surfaces and the exact required changes are in section 3.7. **For outcome A nothing in validated code needs to change.** |
| D10 | Outcome behaviour: A primary; B and C are contingencies that need an owner-approved `server` asset-type change (3.8). |
| D11 | Unmapped or unknown entities are **never guessed**. They stay in the register with `mapping_state = unmapped`, are counted and listed, and get no TwinGrid sensor (a sensor cannot exist without an asset). |
| D12 | The boundary with Task 8 and Task 9 is in section 3.10. |

---

## 3. Decision detail

### 3.1 Dataset identity (D1)

Required fields of the **dataset record** (storage location and format are Task 9; owner decision O-8):

`dataset_id` (`danish-aau-v5`), `name` ("Danish AAU Server-Room"), `version` ("v5"), `doi` (10.5281/zenodo.21262042), `source_url` (https://zenodo.org/records/21262042), `licence` ("CC BY 4.0"), `attribution_text` (the Melgaard et al. text in the Context section 2), `modifications_statement`, `retrieved_date` (2026-10-30, from the existing manifest), `manifest_sha256` (97231727cb3d3d7a96db2fafb1bdfb1f83e40937805db2d02dceb02f42c264cd), `access_status` (owner choice 4 Nov 2026: cloud processing of attached files permitted, derived outputs private, no public demo/API/redistribution until a separate owner decision).

Rules:
- `danish-aau-v5` satisfies the stream-id grammar (`import:danish-aau-v5` is 19 characters, limit 64). Task 9 owns the final stream name; any suffix must stay inside that grammar.
- **The version is part of the namespace.** A future v6 is a new namespace. Physical identity across versions is **not** assumed; an equivalence would be a new, owner-approved mapping record.
- A Facility row and a dataset record are linked by the shared namespace prefix and by the facility name. There is no foreign key (none exists; adding one is a migration, out of scope).

### 3.2 Facility and site (D2)

- **One Facility.** Proposed name (owner wording O-6): `Danish AAU Server-Room v5 - Serverroom (imported dataset; site location not established)`. `Facility.name` is unique and is a label, not evidence of location. It must not be read as "Aalborg" or any city.
- Proposed `frame_note`: "Not established: coordinate frame, origin, orientation, scene-unit factor, geographic location, timezone. No poses are recorded for imported assets. CAD coordinates exist in the source but their unit is not stated; they are not used." (`frame_unit` is forced to `m` by the existing CHECK; the note disclaims any frame.)
- The Facility is **the site**, which here is the room. The "air cavity above" is part of the room; it has **no measurement attributed to it** and is not modelled as an asset.
- If a second physical site ever appears in a source, it gets its own Facility. Sites are never merged to save a row, and an unknown site is never defaulted to the existing one.
- **Creation path:** there is no HTTP route; Task 13/15 would need a repository-level creation script. That is Phase 3, not designed here beyond this constraint.

### 3.3 Source entity classes, IDs and evidence (D3, D4)

Counts below were checked programmatically against the Task 3 table (48 = 37 + 6 + 5; rack split 3,3,3,3,22,3).

| Class | Count | Source key (immutable) | Proposed TwinGrid id (`external_id`) | Evidence (file / column / sheet / image) | Evidence status |
|---|---|---|---|---|---|
| Rack | 6 | source rack number 1..6 | asset `danish-aau-v5.rack.<N>`, type `rack`, name "Rack <N>" | Workbook `AAU-layout-file.xlsx`, sheet `Ark1`, column `Rack`; probe images `Measurement_points_temperature_1.jpg`, `Measurement_points_temperature_2.jpg` | documented in source; CAD `Cabinet N` correspondence **partial** (not used) |
| Rack temperature probe | 37 | CSV header `Temperature mod M ch C` | sensor `danish-aau-v5.temperature.mod<M>.ch<C>`, measurand `temperature`, attached to the rack asset | CSV header; label "name (MODM,C)" on the two probe images; `temperature.png` | rack and front/back from an **agent-read image label**; owner spot-check pending |
| Power channel | 3 | CSV header `Power Ch N (W)` | sensor `danish-aau-v5.power.ch<N>`, measurand `power`, unit W, on asset `danish-aau-v5.pdu.ch<N>` (type `pdu`) | CSV header; workbook column K "Power use measurement port"; `power.png` legend | group membership **documented**; `Ch N` = port N **corroborated, not stated in words** |
| Non-rack temperature probe | 11 (6 cooling-unit, 5 room-gradient) | CSV header `Temperature mod M ch C` | sensor `danish-aau-v5.temperature.mod<M>.ch<C>` on `danish-aau-v5.zone.serverroom` (Tier 2) | CSV header; probe images; `temperature.png` | image labels ("Back cooling window", "Gradient 1", ...); one image typo "Gradient 3 (MOD4.3)" read as (MOD4,3) |
| Air-speed channel | 16 | CSV header `velocity N` | sensor `danish-aau-v5.velocity.<N>` on `danish-aau-v5.zone.serverroom` (Tier 2) | `AAU_air_speed*.csv` header; "Port N" on the velocity images (file names not listed in the supplied inputs); `air_speed.png` (m/s) | `velocity N` = Port N **corroborated** (velocity 1 and 12 ranges fit the plot) |
| Surrounding-temperature file | 6 columns | verbatim CSV header (only `Outdoor_temperature` is quoted in the supplied inputs) | **deferred**; reserved prefix `danish-aau-v5.surround.` | `AAU_supplementary_surrounding_temperatures.csv`; `AAU_DC_surrounding_rooms.png` | room-boundary level; unit **unknown**; 900 s cadence; no resolution declared (protocol `required = false`) |
| Ventilation file | 6 columns | verbatim CSV header | **deferred**; reserved prefix `danish-aau-v5.ventilation.` | `AAU_supplementary_ventilation.csv` | AHU/damper names only; meaning and unit **unknown** |
| Server (inventory note) | not counted | none usable (hostnames are notes) | **no TwinGrid entity** | workbook rows with hostname/model/PSU notes | no measurement channel is per server |

Rack 1-6 probe summary (Tier 1):

| Rack | Asset id | front | back | total |
|---|---|---|---|---|
| Rack 1 | `danish-aau-v5.rack.1` | 1 | 2 | 3 |
| Rack 2 | `danish-aau-v5.rack.2` | 1 | 2 | 3 |
| Rack 3 | `danish-aau-v5.rack.3` | 1 | 2 | 3 |
| Rack 4 | `danish-aau-v5.rack.4` | 1 | 2 | 3 |
| Rack 5 | `danish-aau-v5.rack.5` | 4 | 18 | 22 |
| Rack 6 | `danish-aau-v5.rack.6` | 1 | 2 | 3 |
| **Total** | | **9** | **28** | **37** |

Full per-channel tables are in Appendix A. The Task 3 register (`task3_identity_register.csv`, 79 rows) and `TASK_3_REPORT.md` were **not supplied**; the Appendix A rows come from the Context transcription of the same register. 48 + 3 + 16 + 12 = 79 is consistent with the register's row count but that was **not verified** against the file.

### 3.4 ID and uniqueness rules (D4, D5)

1. **Namespace.** Every imported `asset.external_id` and `sensor.external_id` begins with `danish-aau-v5.`. Characters: lowercase ASCII `[a-z0-9.-]`. Maximum 128 (DB limit); real ids are well under 60.
2. **Source key only.** The variable part is taken from the CSV header text or the source rack number by a fixed template (table in 3.3), e.g. header `Temperature mod 7 ch 3` becomes `danish-aau-v5.temperature.mod7.ch3`. No zero padding, no sorting, no counter, no hash, no row index.
3. **No interpretation in IDs.** Rack number, front/back, probe class and group membership are not in sensor ids. If an image label is corrected, the id stays and only the mapping record changes (but see rule 7).
4. **No DB integer ids.** Contrast the demo `fac<facility_id>.<measurand>`, which embeds a DB id. Imported ids must be reproducible on any database.
5. **Collision-free by construction and by test.** The prefix `danish-aau-v5.` cannot match the demo patterns (`zone-<n>`, `zone-<n>-row-<n>-rack-<n>`, `facility-level`, `fac<digits>.`). A validator (Task 13) must assert: every id matches its class regex; the set of ids is unique; no id matches a demo pattern; any normalisation (needed only for the deferred supplementary headers: lowercase, each run of characters outside `[a-z0-9]` becomes `-`, trim `-`) produces no duplicates.
6. **Immutable and never reused.** A retired entity keeps its id (`retired_at` exists on `Asset` and `Sensor`).
7. **Correction policy.** Before any sensor row exists, a label correction is a new mapping version. After sensors and samples exist, `Sensor.asset_id` encodes the attachment, and there is no service to move a sensor. The corrected entity is then retired and replaced under a new id suffix (`.r2`), and Task 9 decides what happens to the samples already stored. **Consequence: the owner spot-check of the 48 labels should finish before Task 15 creates sensors** (O-2).
8. **Facility-scoped vs global.** `Asset` ids only need to be unique inside the facility; `Sensor` ids are global and so are the only ones where a collision with the demo is possible. The prefix covers both.
9. **Source words stay source words.** The register keeps `source_label` verbatim ("Rack 5 back L5", "Cooling wall Front L", "Rack 4+6") and `source_position_word` (`front`/`back`). **No field, measurand or asset name is called inlet, outlet, supply or return.** The measurand is the neutral `temperature` (the CSV header word).

### 3.5 Attachment rules (D6)

| Entity | Attached to | Why |
|---|---|---|
| Rack probe (37) | its rack asset (`danish-aau-v5.rack.<N>`) | The source labels the probe with a rack. Several sensors of one measurand on one asset is allowed (no unique `(asset, measurand)` constraint). |
| Power channel (3) | power-port asset `danish-aau-v5.pdu.ch<N>`; **never a rack** | Prevents any query "sensors of Rack 1" from returning a group value. Type `pdu` is the nearest existing type and the only one that satisfies `powered_by` should edges be added later. It does **not** assert a PDU device model; the source word is "measurement port" (O-3). |
| Non-rack probe (11), air speed (16) | one room-scope asset `danish-aau-v5.zone.serverroom`, type `zone`, only if Tier 2 is approved | No rack attribution. They are never attached to a rack asset. |
| Supplementary (12) | not materialised | Units unknown, no resolution declared, not screened. |

**File is not identity.** The seven `AAU_temperature_and_power_use*.csv` files carry the *same* 51 channels; the period files are subsets of the full file. There is **one sensor per channel**, not one per file. File and column are lineage (Task 8).

### 3.6 Time-valid mappings and evidence fields (D8)

**Why no `asset_edge` or `asset_pose` rows for imported assets in v1.**
- `valid_from` is NOT NULL and the service defaults an omitted value to *now*; a future value is refused. The only instants the source gives are **naive timestamps with an undeclared timezone**, so no UTC instant for "the layout held from..." can be derived without inventing a timezone.
- A record-time `valid_from` (the import date) would assert a relationship from 2026 onward, which is not what the source says either. The seed script already follows this principle: relationships start at the recording time "because as-of queries must not claim this layout existed before it was recorded".
- Poses need `x, y, z` NOT NULL. No source-backed coordinate exists. Without a pose the asset is excluded from the default `/api/assets` listing (`include_unplaced = false`) and is available only with `include_unplaced = true`.

**Therefore** the attribution facts live in the **mapping register**, a versioned record per source entity, and imported history is attributed by the **mapping id and version pinned at import time**, never by an `as_of` edge lookup. (O-5 records the alternative.)

**Mapping record fields (identity side):**

| Field | Meaning |
|---|---|
| `mapping_id` | `danish-aau-v5.map.<source_entity_id>` (deterministic) |
| `mapping_version`, `status` | integer; `active` / `superseded` / `withdrawn`. Versions are immutable; a revision is a new version. |
| `dataset_id`, `source_entity_class`, `source_entity_id` | which source entity |
| `target_kind`, `target_asset_external_ids[]`, `sensor_external_id` | where it lands; **a list**, so a group is explicit |
| `cardinality` | `one_to_one` or `many_to_one` |
| `attribution_scope` | `rack`, `rack_group`, `single_rack_port`, `room_scope`, `none` |
| `split_allowed` | `false` for every group channel |
| `evidence_refs[]` | file, sheet and cell range, column, image name, CAD layer (each with SHA-256 where a file exists) |
| `evidence_status` | `documented_in_source`, `corroborated_not_stated`, `partial`, `not_established` |
| `label_provenance` | `agent_transcribed` or `owner_verified` (image labels start as `agent_transcribed`) |
| `source_label`, `source_position_word` | verbatim source words |
| `valid_time_status` | `not_established` (all v1 records), `owner_asserted`, `source_documented` |
| `valid_from_text`, `valid_to_text` | nullable **source-text** bounds; filled only if the status is not `not_established`; **no UTC value unless the timezone is documented and approved** |
| `applied_uniformly_over_window` | `true` = explicit assumption used so one sensor can carry the whole observation window (O-1) |
| `observation_window_text` | informational copy of Task 4 (full file 2024-09-16 16:58:30 to 2024-10-02 13:53:02, naive); **not** a validity claim |
| `decided_by`, `decided_on`, `supersedes` | owner decision trail |

Neutral field names above are proposals for the **identity** side; Task 8 owns the final telemetry-record field names and must carry `mapping_id` and `mapping_version`.

### 3.7 Separation from the 36 simulated demo racks (D9)

**Rule:** no imported entity is mapped, aliased, linked or edge-connected to any demo rack, zone, sensor or facility. No imported value is shown under a demo rack id. The demo racks are `zone-<n>-row-<n>-rack-<n>` in "Default Facility"; the imported racks are `danish-aau-v5.rack.<N>` in another Facility.

**What would collide or need change, verified in the repository** (details and lines in Appendix C):

| Surface | Collision? | Required handling |
|---|---|---|
| `facility.name` unique | No: names differ | None |
| `asset (facility_id, external_id)` unique | No: separate facility and different pattern | None |
| `sensor.external_id` globally unique | No, **because of the `danish-aau-v5.` prefix**; demo ids are `fac<id>.<measurand>` | Validator (3.4 rule 5) |
| `ASSET_TYPES` | **No change for outcome A**: `rack`, `pdu`, `zone` are all valid | None for A; `server` only for B/C (3.8) |
| Default facility = **lowest id** (`get_facility(None)`, used by `/api/facility`, `/api/assets`, the frontend which sends no `facility_id`) | **Yes, ordering risk.** If the dataset Facility is created first on an empty database it takes id 1 and becomes the default facility. | The demo Facility must exist (lower id) before the dataset Facility is created. Every dataset endpoint (Task 9/16) must require an explicit facility. Never rely on the default. |
| `TELEMETRY_FACILITY_ID` default 1 and `fac<id>.*` | Same ordering risk | Same rule; imported sensors are never named `fac<n>.*` |
| `/api/assets` hides unplaced assets by default; frontend never requests `include_unplaced` | Protective, not a collision | Imported racks have no poses, so the 3D scene cannot render them even if their facility were selected |
| `frame_unit` CHECK = 'm' | Forces a metre label on a facility with no frame | `frame_note` disclaims the frame (3.2) |
| Out-of-vocabulary type `"facility"` already in the DB (seed `facility-level` asset, written via the repository, bypassing `ASSET_TYPES`) | Latent inconsistency, not a collision | Imported assets use only validated types. Note: an asset of an invalid type cannot be filtered with `/api/assets?asset_type=` (422). |
| `WorkOrder.asset_external_id` is not facility-scoped | Possible ambiguity for short ids | Prefix prevents it |
| Default `stream = live` and retention | Imported history must never read from `live`; retention does not purge `import:` | Task 9/16 |
| Tests that pin the 36 racks (`test_ig05_rack_id_parity.py`, `test_facility_seed.py`) | They seed and count only the default facility | Not affected, provided the imported facility is not created inside those fixtures |

Sensors created through `facility_service.create_sensor` or `repo.insert_sensor` receive `source_tz = 'UTC'` from the column default. That would silently assert a timezone for a source whose timezone is undeclared. Handling belongs to Task 8/9 (flagged in 3.10); the ADR's identity requirement is only that **no imported sensor may be registered with an assumed timezone**.

### 3.8 Behaviour for outcomes A, B and C (D10)

**A. Rack-capable (accepted; primary design).** Everything in 3.1-3.7. Granularity delivered: rack temperature probes (rack-level, per probe) and rack-**group** power. Limits carried forward from Task 6: power is group-level only; Racks 1-3 and 4+6 are never split; per-rack power exists only for Rack 5 (via its own port); no server level; front/back are source words; rack identity is from agent-read labels pending spot-check; CAD cabinets not equated to racks; one room, six racks, about 16 days.

**B. Server-to-rack capable (contingency; no server data exists in v5).** Applies only if a source supplies server-level measurements **and** a documented server-to-rack map. The **minimum change** to the existing model:

| Component | Minimum change | Effect |
|---|---|---|
| `api/services/facility_service.py` `ASSET_TYPES` | add `"server"` | No migration (`asset_type` is TEXT). `/api/assets?asset_type=server` becomes valid. The existing 422 test uses `"spaceship"` and is unaffected. |
| `RELATIONS` | add `"installed_in"` (12 characters; column is 16) | `located_in` cannot be reused: its parent must be a `zone`, and the partial unique index allows one open `located_in` per child, so a server could not be in a zone and a rack. |
| `_check_edge_types` | new branch: `installed_in` parent must be `rack`, child must be `server`, same facility, neither retired | Service-level only. The DB partial unique indexes cover `located_in` and the open (child, parent, relation) triple; "one open `installed_in` per server" would be **service-enforced only** unless an Alembic index is added (separate approval). |
| Frontend | none required | `asset_type` is `z.string()`; the 3D model reads only `zone` and `rack`. |
| Demo seed and 36 racks | none | No servers are seeded. |
| Naming risk | `fac<n>.server_outlet_temp_C` is a facility-level measurand, not a server asset | Documentation must keep them apart. |

Under B, server ids are `danish-aau-v5.server.<documented server key>` (the key must be a source-documented identifier, never a row number), sensors attach to the server, and rack values are **derived proxies only**, labelled `derived`, held outside `telemetry_sample` as measured rows (Task 9). Any change above is outside this task and needs owner approval at G1.

**C. Server-only fallback.** Applies if server-level measurements exist but no documented server-to-rack map exists. Same `server` type change as B; servers are `located_in` the room zone (allowed by the current rule: parent zone, child not a zone) with **no rack parent**, no rack proxies and server-level labels in the product. Per the Master Handoff, the owner must explicitly approve changing the deliverable to server-only. A dataset verdict C (neither rack nor server capability) stops Phase 3 for this dataset. Not applicable to v5 as accepted.

**Applicability to v5:** A only. B and C are documented so a future dataset or an owner-supplied server log does not force a redesign.

### 3.9 Many-to-one attribution without implying per-rack values (D7)

- Each power channel is **one sensor on one power-port asset**. No power sensor is attached to Racks 1-4 or 6. Rack 5's channel is also on its own port asset (uniform with the others); it is **not** duplicated as a rack-attached sensor.
- The mapping record carries `target_asset_external_ids = [racks...]`, `cardinality = many_to_one`, `attribution_scope = rack_group`, `split_allowed = false`, and the source group label verbatim:

| Channel | Source group label | Member racks | Scope |
|---|---|---|---|
| `Power Ch 1` | "Rack 1-3" | 1, 2, 3 | `rack_group` |
| `Power Ch 2` | "Rack 4+6" | 4, 6 (never "Rack 4-6") | `rack_group` |
| `Power Ch 3` | "Rack 5" | 5 | `single_rack_port` |

- A consumer asking for the power of Rack 1 gets the group record (members 1, 2, 3) and **no** per-rack number. A per-rack power field may only be offered where `member count = 1` (Rack 5), and its evidence status is inherited (`corroborated_not_stated`).
- Forbidden at the identity layer: dividing a group value, equal-splitting, naming a group channel with one rack's id, or summing groups into a room total here. The paper's "split evenly per server" statement is **not** applied. Any future split would be a `derived` proxy needing a documented server-to-rack map (absent), the formula and owner approval.

### 3.10 Unmapped and unknown entities (D11) and the Task 8 / Task 9 boundary (D12)

**Handling.** Every source entity gets `mapping_state`: `mapped`, `mapped_partial`, `unmapped`, `not_applicable`. Unmapped entities are listed in the register and reported by count; they get no asset and no sensor (a sensor needs an asset), and their samples are never loaded as rack telemetry. The reader may read them for the panel with `identity_status = unmapped`, but no loader may place them on any asset. An ambiguous or missing mapping fails the validator (Task 13); it is never resolved by label similarity or position.

Current inventory:

| Group | Count | State | Note |
|---|---|---|---|
| Racks 1-6 | 6 | mapped | |
| Rack probes | 37 | mapped (label provenance `agent_transcribed`) | |
| Power channels | 3 | mapped (group scope) | |
| Non-rack temperature probes | 11 | mapped to room scope (Tier 2) | |
| Air-speed channels | 16 | mapped to room scope (Tier 2) | |
| Supplementary columns | 12 | `mapped_partial` (scope only; units unknown); deferred | |
| **Tier 1 unmapped** | **0** | | |
| Server inventory rows | count not established in the supplied inputs | `not_applicable` (no measurement) | includes "Unknown server/PC" and "?" rows |
| CAD objects | 75 (48 PT100, 16 Anemometer, 6 `Cabinet N`, 2 Fancoil, Lockers, Radiator inclosure, handle `2d9` without position) | not linked to channels (image labels are the channel mapping) | `Cabinet N` = Rack N is partial, not used; CAD coordinates unit not stated |
| `_3d/` STL files | 5 | outside the manifest, origin unconfirmed | not used |
| Cooling units (2 fancoils in CAD) | 2 | **no asset** | Mapping a fancoil to `crac` would be a guess; not done |

**Task 7 owns:** dataset identity fields, Facility/site rule, entity classes, id grammar and uniqueness, attachment rules, the mapping record's semantics and evidence/time-validity vocabulary, outcome A/B/C behaviour, unmapped handling, the demo-separation rules.

**Task 8 owns (this ADR does not define):** typed telemetry record fields and API response shapes; provenance labels as record fields; quality, missing, invalid and stale states; timestamp text vs UTC fields; units and the unit of each measurand; source file/column/row reference format; cleaning-ledger disposition fields; derived-value formula fields; example payloads. Task 8 must carry `sensor_external_id`, `asset_external_id`, `mapping_id`, `mapping_version`, `dataset_id`.

**Task 9 owns (this ADR does not decide):** where the dataset record and mapping register are stored; how facility, asset and sensor rows are created (no route exists); `Sensor.source_tz` and `naive_policy` handling for undeclared timezone data; stream naming beyond `import:danish-aau-v5`; origin value for imported rows (`measured`/`replay` vs the four provenance labels); the separate store for derived values; query semantics (explicit facility and stream, no fallback to `live`); retention, access control and licence enforcement; the handling of stored samples after a label correction; whether Tier 2 and supplementary data are loaded.

---

## 4. Alternatives considered

| # | Alternative | Why not chosen |
|---|---|---|
| 1 | Map the six racks onto six of the 36 demo racks | Forbidden by the handoff (no physical correspondence is proven) and it would show 2024 measurements under simulated rack ids. |
| 2 | Put the dataset in the existing "Default Facility" under a new zone | Mixes a measured site with a simulated one; `asset (facility, external_id)` and the default-facility behaviour would blur the boundary. |
| 3 | Encode rack, front/back or class in sensor ids (e.g. `rack2.front.temp`) | Interpretation is evidence-dependent and the labels are agent-read; a correction would break id stability. It also tempts inlet/outlet naming. |
| 4 | Attach the group power sensors to one rack of the group, or to all members | Implies a per-rack value; duplicates a single channel; breaks the "never split" rule. |
| 5 | Add a `rack_group` or `power_channel` asset type | Cleaner semantics, but it is an asset-validation change, which this task may not make. Kept as owner option O-3. |
| 6 | Create `asset_edge` rows (`powered_by`, `located_in`) with `valid_from` = import time | Asserts a 2026 relationship for 2024 data and cannot express "validity not established". Kept as owner option O-5. |
| 7 | Use a sentinel `valid_from` (for example the first CSV timestamp as UTC) | Requires inventing a timezone. Rejected. |
| 8 | One sensor per CSV file/period | The period files are subsets of the full file (Task 6); it would multiply identities and invite double counting. |
| 9 | Model cooling units as `crac` assets | The source says only "cooling wall/window" (CAD: fancoil); `crac` is a guess. |
| 10 | Use the out-of-vocabulary `"facility"` type as the seed does for non-rack channels | Repeats a validator bypass; `/api/assets?asset_type=facility` would 422. Room-scope `zone` is used instead (semantic stretch for outdoor/ventilation is why those 12 are deferred). |
| 11 | Treat a rack-group channel as per-rack by even split ("per server" in the paper) | Unsupported: no server map exists; the discrepancy is unresolved. |

## 5. Consequences

**Positive.** Outcome A needs **no** change to validated code, schema, migrations, origin enum or any frozen path. Imported identity cannot collide with the demo, cannot appear in the 3D scene by accident, and cannot be mistaken for per-rack power. IDs are reproducible on any database. Interpretation can be corrected by a new mapping version without renaming sensors (before materialisation).

**Negative / costs.**
- Attribution lives in a register outside the database in v1; Task 9 must provide a read path so the API can state group membership.
- Without edges, "which racks does sensor X cover" is not answerable from `/api/assets/{id}/edges`.
- A label correction after materialisation costs a retire-and-replace.
- Using `pdu` for a measurement port and `zone` for room-scope scope is a semantic approximation, disclosed in names and in the register.
- All imported assets are unplaced; the product cannot show them in the 3D view (consistent with the handoff: no invented coordinates).

**Risks to watch.** Default-facility ordering (3.7). Silent `source_tz = 'UTC'` on sensor creation. Image-label provenance (agent-read; `_mv` origin unconfirmed). The "front"/"back" words being read as inlet/outlet by later UI text.

## 6. Open questions for the owner

| # | Question | Default if not answered |
|---|---|---|
| O-1 | Accept **uniform application of one undated mapping over the whole observation window** as a recorded assumption (`valid_time_status = not_established`)? Or obtain layout-date evidence first (the paper was never opened by Task 3)? | Block Phase 3 identity loading until answered |
| O-2 | Complete the owner spot-check of the 48 temperature labels (and the 16 "Port N" labels) **before Task 15** creates sensors? | Labels stay `agent_transcribed`; no materialisation claim of "owner verified" |
| O-3 | Reuse existing type `pdu` for the power-measurement port (zero change), or approve a new asset type? Is "PDU" acceptable wording given the source says "measurement port"? | `pdu`, with the name "Power measurement port N (source: Power Ch N)" |
| O-4 | Materialise Tier 2 (11 non-rack probes, 16 air-speed channels)? Supplementary files stay deferred until units and resolution are set (`required = true`). | Register only; do not materialise |
| O-5 | No `asset_edge` rows in v1 (recommended), or record-time-valid edges? | None |
| O-6 | Approve the Facility name and `frame_note` wording; approve a repository-level creation script for Phase 3 (no route exists). | As proposed |
| O-7 | Accept `Power Ch N` = port N and `velocity N` = "Port N" as **corroborated** (not stated in words), consistent with the accepted G-DS scope? | Carried as `corroborated_not_stated` |
| O-8 | Where should the dataset record and mapping register live (extend `docs/datasets/danish-server-room-v5/manifest.json`, or a new versioned file)? Decided with Task 9. | Task 9 proposes |
| O-9 | Approve `dataset_id = danish-aau-v5` and the rule that a new dataset version is a new namespace. | As proposed |
| O-10 | The paper's "power split per server" vs 3 channels for 6 racks remains unresolved. Any author clarification or supplementary evidence? | Remains open; never split |
| O-11 | Confirm the owner's name spelling for records: Context section 2 says "Lakshay" (licence evidence), protocol approval says "Lakshya Aggarwal". | Use "the owner" |
| O-12 | Confirm the `_mv` images are byte-identical to the manifest zip members (the identity evidence relies on them); `task3_evidence.txt` zip member lists could settle this. | Recorded as an evidence-chain caveat |

## 7. Evidence table

| Claim | Evidence | Status |
|---|---|---|
| G-DS = A, three pair dispositions accepted | Task 7 instruction; `TASK_06_REPORT.md` sections 3-6 | owner statement in the instruction; not independently verifiable here |
| Protocol locked | `research/danish_aau/protocol/protocol_v1.toml` (LF-normalised SHA-256 recomputed on the supplied zip = `0ff45216...7098`, matches the Task 6 report and Context) | verified here |
| Task 6 runner as reported | `research/danish_aau/screening/run_task6_screen.py` SHA-256 recomputed = `684f2fb0...ecc7` (matches the report) | verified here (hash only; not re-run, raw data not supplied) |
| One site, six racks, 37/11 probe split, 3 power channels, 16 air-speed | Context section 4 (Task 3); counts re-derived from its table | transcribed evidence; the Task 3 report/register not supplied |
| Rack 5 = 4 front + 18 back; other racks 1 + 2 | Context section 4 table | transcribed evidence |
| Power group membership | workbook column K; `power.png` legend | transcribed evidence |
| Period files are subsets | `TASK_06_REPORT.md` section 3 | owner-run result |
| Repository facts | Appendix C | read in the supplied zip; **no test or code was executed** |
| Layout time validity, timezone, front=inlet, Cabinet = Rack | Context section 4 "Not established" | not established |

---

## Appendix A. Per-channel identity table (generated from the Task 3 table in the Context)

### A.1 Temperature channels (48)

| CSV column | Proposed sensor `external_id` | Source image label | Rack (source) | Position word (source) | Class | Attached to |
|---|---|---|---|---|---|---|
| `Temperature mod 1 ch 1` | `danish-aau-v5.temperature.mod1.ch1` | Rack 2 front | Rack 2 | front | rack_probe | asset `danish-aau-v5.rack.2` (Tier 1) |
| `Temperature mod 1 ch 2` | `danish-aau-v5.temperature.mod1.ch2` | Rack 6 back 1 | Rack 6 | back | rack_probe | asset `danish-aau-v5.rack.6` (Tier 1) |
| `Temperature mod 1 ch 3` | `danish-aau-v5.temperature.mod1.ch3` | Rack 5 front 1 | Rack 5 | front | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 1 ch 4` | `danish-aau-v5.temperature.mod1.ch4` | Rack 5 front 2 | Rack 5 | front | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 1 ch 5` | `danish-aau-v5.temperature.mod1.ch5` | Rack 5 front 3 | Rack 5 | front | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 1 ch 6` | `danish-aau-v5.temperature.mod1.ch6` | Rack 4 front | Rack 4 | front | rack_probe | asset `danish-aau-v5.rack.4` (Tier 1) |
| `Temperature mod 1 ch 7` | `danish-aau-v5.temperature.mod1.ch7` | Rack 6 front | Rack 6 | front | rack_probe | asset `danish-aau-v5.rack.6` (Tier 1) |
| `Temperature mod 1 ch 8` | `danish-aau-v5.temperature.mod1.ch8` | Rack 3 front | Rack 3 | front | rack_probe | asset `danish-aau-v5.rack.3` (Tier 1) |
| `Temperature mod 2 ch 1` | `danish-aau-v5.temperature.mod2.ch1` | Rack 5 back L5 | Rack 5 | back | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 2 ch 2` | `danish-aau-v5.temperature.mod2.ch2` | Rack 5 back L3 | Rack 5 | back | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 2 ch 3` | `danish-aau-v5.temperature.mod2.ch3` | Rack 6 back 2 | Rack 6 | back | rack_probe | asset `danish-aau-v5.rack.6` (Tier 1) |
| `Temperature mod 2 ch 4` | `danish-aau-v5.temperature.mod2.ch4` | Rack 5 back L6 | Rack 5 | back | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 2 ch 5` | `danish-aau-v5.temperature.mod2.ch5` | Rack 5 back L4 | Rack 5 | back | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 2 ch 6` | `danish-aau-v5.temperature.mod2.ch6` | Rack 5 back L2 | Rack 5 | back | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 2 ch 7` | `danish-aau-v5.temperature.mod2.ch7` | Rack 1 front | Rack 1 | front | rack_probe | asset `danish-aau-v5.rack.1` (Tier 1) |
| `Temperature mod 2 ch 8` | `danish-aau-v5.temperature.mod2.ch8` | Rack 5 back L1 | Rack 5 | back | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 3 ch 1` | `danish-aau-v5.temperature.mod3.ch1` | Back cooling window | none | cooling unit | cooling_unit_probe | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `Temperature mod 3 ch 2` | `danish-aau-v5.temperature.mod3.ch2` | Back cooling wall | none | cooling unit | cooling_unit_probe | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `Temperature mod 3 ch 3` | `danish-aau-v5.temperature.mod3.ch3` | Rack 5 back L7 | Rack 5 | back | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 3 ch 4` | `danish-aau-v5.temperature.mod3.ch4` | Rack 5 back R1 | Rack 5 | back | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 3 ch 5` | `danish-aau-v5.temperature.mod3.ch5` | Rack 5 back R3 | Rack 5 | back | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 3 ch 6` | `danish-aau-v5.temperature.mod3.ch6` | Rack 5 back L8 | Rack 5 | back | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 3 ch 7` | `danish-aau-v5.temperature.mod3.ch7` | Rack 5 back L9 | Rack 5 | back | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 3 ch 8` | `danish-aau-v5.temperature.mod3.ch8` | Rack 5 back R2 | Rack 5 | back | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 4 ch 1` | `danish-aau-v5.temperature.mod4.ch1` | Gradient 1 | none | room | room_gradient_probe | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `Temperature mod 4 ch 2` | `danish-aau-v5.temperature.mod4.ch2` | Gradient 2 | none | room | room_gradient_probe | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `Temperature mod 4 ch 3` | `danish-aau-v5.temperature.mod4.ch3` | Gradient 3 | none | room | room_gradient_probe | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `Temperature mod 4 ch 4` | `danish-aau-v5.temperature.mod4.ch4` | Gradient 5 | none | room | room_gradient_probe | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `Temperature mod 4 ch 5` | `danish-aau-v5.temperature.mod4.ch5` | Gradient 4 | none | room | room_gradient_probe | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `Temperature mod 4 ch 6` | `danish-aau-v5.temperature.mod4.ch6` | Rack 5 back R4 | Rack 5 | back | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 4 ch 7` | `danish-aau-v5.temperature.mod4.ch7` | Rack 5 back R6 | Rack 5 | back | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 4 ch 8` | `danish-aau-v5.temperature.mod4.ch8` | Rack 5 back R5 | Rack 5 | back | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 5 ch 1` | `danish-aau-v5.temperature.mod5.ch1` | Rack 5 back R7 | Rack 5 | back | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 5 ch 2` | `danish-aau-v5.temperature.mod5.ch2` | Rack 5 back R8 | Rack 5 | back | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 5 ch 3` | `danish-aau-v5.temperature.mod5.ch3` | Rack 5 back R9 | Rack 5 | back | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 5 ch 4` | `danish-aau-v5.temperature.mod5.ch4` | Rack 4 back 1 | Rack 4 | back | rack_probe | asset `danish-aau-v5.rack.4` (Tier 1) |
| `Temperature mod 6 ch 1` | `danish-aau-v5.temperature.mod6.ch1` | Rack 2 back 1 | Rack 2 | back | rack_probe | asset `danish-aau-v5.rack.2` (Tier 1) |
| `Temperature mod 6 ch 2` | `danish-aau-v5.temperature.mod6.ch2` | Rack 3 back 2 | Rack 3 | back | rack_probe | asset `danish-aau-v5.rack.3` (Tier 1) |
| `Temperature mod 6 ch 3` | `danish-aau-v5.temperature.mod6.ch3` | Rack 3 back 1 | Rack 3 | back | rack_probe | asset `danish-aau-v5.rack.3` (Tier 1) |
| `Temperature mod 6 ch 4` | `danish-aau-v5.temperature.mod6.ch4` | Rack 4 back 2 | Rack 4 | back | rack_probe | asset `danish-aau-v5.rack.4` (Tier 1) |
| `Temperature mod 7 ch 1` | `danish-aau-v5.temperature.mod7.ch1` | Rack 5 front 4 | Rack 5 | front | rack_probe | asset `danish-aau-v5.rack.5` (Tier 1) |
| `Temperature mod 7 ch 2` | `danish-aau-v5.temperature.mod7.ch2` | Rack 1 back 2 | Rack 1 | back | rack_probe | asset `danish-aau-v5.rack.1` (Tier 1) |
| `Temperature mod 7 ch 3` | `danish-aau-v5.temperature.mod7.ch3` | Rack 1 back 1 | Rack 1 | back | rack_probe | asset `danish-aau-v5.rack.1` (Tier 1) |
| `Temperature mod 7 ch 4` | `danish-aau-v5.temperature.mod7.ch4` | Rack 2 back 2 | Rack 2 | back | rack_probe | asset `danish-aau-v5.rack.2` (Tier 1) |
| `Temperature mod 8 ch 1` | `danish-aau-v5.temperature.mod8.ch1` | Cooling wall Front R | none | cooling unit | cooling_unit_probe | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `Temperature mod 8 ch 2` | `danish-aau-v5.temperature.mod8.ch2` | Cooling wall Front L | none | cooling unit | cooling_unit_probe | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `Temperature mod 8 ch 3` | `danish-aau-v5.temperature.mod8.ch3` | Cooling window Front R | none | cooling unit | cooling_unit_probe | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `Temperature mod 8 ch 4` | `danish-aau-v5.temperature.mod8.ch4` | Cooling window Front L | none | cooling unit | cooling_unit_probe | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |

### A.2 Power channels (3)

| CSV column | Sensor `external_id` | Power-port asset | Source group label | Member racks | Scope |
|---|---|---|---|---|---|
| `Power Ch 1 (W)` | `danish-aau-v5.power.ch1` | `danish-aau-v5.pdu.ch1` | Rack 1-3 | 1, 2, 3 | rack_group |
| `Power Ch 2 (W)` | `danish-aau-v5.power.ch2` | `danish-aau-v5.pdu.ch2` | Rack 4+6 | 4, 6 | rack_group |
| `Power Ch 3 (W)` | `danish-aau-v5.power.ch3` | `danish-aau-v5.pdu.ch3` | Rack 5 | 5 | single_rack_port |

The exact CSV header text (for example whether the unit suffix is `(W)`) was not quoted verbatim in the supplied inputs; the reader (Task 11) must take it from the file and fail on a mismatch.

### A.3 Air-speed channels (16)

| CSV column | Sensor `external_id` | Source label | Attached to |
|---|---|---|---|
| `velocity 1` | `danish-aau-v5.velocity.1` | Cooling wall (Port 1) | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `velocity 2` | `danish-aau-v5.velocity.2` | Mount L 1 (Port 2) | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `velocity 3` | `danish-aau-v5.velocity.3` | Mount L 2 (Port 3) | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `velocity 4` | `danish-aau-v5.velocity.4` | Mount L 3 (Port 4) | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `velocity 5` | `danish-aau-v5.velocity.5` | Mount M 2 (Port 5) | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `velocity 6` | `danish-aau-v5.velocity.6` | Mount M 3 (Port 6) | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `velocity 7` | `danish-aau-v5.velocity.7` | Mount R 3 (Port 7) | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `velocity 8` | `danish-aau-v5.velocity.8` | Front 4 (Port 8) | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `velocity 9` | `danish-aau-v5.velocity.9` | Front 1 (Port 9) | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `velocity 10` | `danish-aau-v5.velocity.10` | Front 2 (Port 10) | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `velocity 11` | `danish-aau-v5.velocity.11` | Front 3 (Port 11) | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `velocity 12` | `danish-aau-v5.velocity.12` | Cooling window (Port 12) | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `velocity 13` | `danish-aau-v5.velocity.13` | Mount M 1 (Port 13) | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `velocity 14` | `danish-aau-v5.velocity.14` | Mount R 2 (Port 14) | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `velocity 15` | `danish-aau-v5.velocity.15` | Mount R 1 (Port 15) | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |
| `velocity 16` | `danish-aau-v5.velocity.16` | Front 5 (Port 16) | asset `danish-aau-v5.zone.serverroom` (Tier 2, optional) |

### A.4 Supplementary files (12 columns): reserved, deferred

Surrounding temperatures: outdoor, adjacent west, adjacent east, above west, above east, below (only `Outdoor_temperature` is quoted verbatim in the supplied inputs). Ventilation: six AHU/damper columns (names not quoted in the supplied inputs). Ids will follow `danish-aau-v5.surround.<normalised header>` and `danish-aau-v5.ventilation.<normalised header>` once the verbatim headers are taken from the files.

## Appendix B. Planned TwinGrid rows if Tier 1 is implemented (design count, nothing created)

| Row type | Count | Notes |
|---|---|---|
| Facility | 1 | created after the demo Facility |
| Asset `rack` | 6 | `danish-aau-v5.rack.1` .. `danish-aau-v5.rack.6` |
| Asset `pdu` (power port) | 3 | `danish-aau-v5.pdu.ch1` .. `ch3` |
| Sensor, rack probes | 37 | measurand `temperature` |
| Sensor, power | 3 | measurand `power`, unit as stated by the source (W) |
| `asset_edge`, `asset_pose` | 0 | see 3.6 |
| Optional Tier 2 | 1 `zone` asset + 27 sensors | owner decision O-4 |

## Appendix C. Repository verification (read in the supplied zip; nothing executed)

| Fact | Location |
|---|---|
| `ASSET_TYPES`, `RELATIONS` | `api/services/facility_service.py` lines 40-41 |
| Edge-type rules (`located_in` parent zone; `powered_by` parent pdu/ups; `serves`) | same file, `_check_edge_types`, line 115 |
| `valid_from` defaults to now; future refused | same file, `_resolve_instant`, line 102; `FUTURE_SKEW`, line 47 |
| `create_asset`, `create_sensor` (service, no route) | same file, lines 209, 227 |
| `Facility` (unique name, `frame_unit` CHECK) | `models/db_models.py` line 493 |
| `Asset` (unique `(facility_id, external_id)`, `retired_at`) | same file, line 508 |
| `AssetEdge`, `AssetPose` (NOT NULL `valid_from`; poses need x, y, z) | same file, lines 527, 565 |
| `Sensor` (global unique `external_id`, `source_tz` default UTC, no label column) | same file, line 594 |
| `TelemetrySample` origin/quality/unique key | same file, lines 623-660 |
| Stream grammar; origins | `src/telemetry/validation.py` lines 42-55 |
| Retention excludes `import:`/`replay:` | `src/telemetry/retention.py` module docstring |
| Lowest-id default facility | `api/repositories/facility_repository.py` line 48 |
| Routes: only GET facility/assets/edges and POST move/edges/close | `api/routes/facility_routes.py` lines 177-393 |
| `insert_sensor` has no `source_tz` parameter | `api/repositories/facility_repository.py` line 331 |
| 36 demo racks, "Default Facility", `facility-level` asset of type `"facility"`, `fac<id>.<measurand>` | `scripts/seed_facility.py` lines 46, 182-187 |
| `TELEMETRY_FACILITY_ID` default 1 | `api/config.py` lines 362, 401-414 |
| Frontend requests topology without `facility_id`/`include_unplaced`; renders only `zone` and `rack` | `twin-stream-insight-main/src/api/facility.ts` header; `src/three/facilityModel.ts` |
| Backend/frontend rack-id parity (demo only) | `docs/adr/005-rack-id-parity.md`; `tests/test_ig05_rack_id_parity.py` |
| Unknown `asset_type` filter returns 422 | `tests/api/test_routes_facility.py` line 290 |
