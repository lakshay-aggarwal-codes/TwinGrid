# TwinGrid canonical telemetry and provenance contract (Task 8)

**Contract id:** `twingrid.rack_telemetry` | **Version:** `1.0.0-draft` | **Status: Ready for review** (owner approves; Tasks 11-17 reference it after approval)
**Prepared:** 5 November 2026 | **Executable form:** `research/danish_aau/contract/telemetry_contract.py` (stdlib-only reference validator), 17 synthetic examples in `contract/examples/`, 89 declarative negative vectors in `contract/negative_vectors.py`.

If this text and the validator disagree, the validator and its tests are authoritative and this document has a bug.

## 1. Authority and inputs

| Input | Identity |
|---|---|
| Locked protocol (Task 5) | `protocol_v1.toml` v1.0.0, SHA-256 `0ff4521697f81c397c81f1af5686284f505956cc239a67b6fe1605adc7b47098` |
| G-DS verdict (Task 6) | **A**, accepted by the owner: rack-capable for rack-labelled temperature, power is rack-**group** only, no server data |
| Identity ADR (Task 7) | `TASK_07_ADR.md`, SHA-256 `8f13794cde8c8be6897c8968548f2bd3eee842b97dc7c4e951daa7edf4ccf458`, approved with recommended answers |
| Master Handoff | sections 4.1-4.3 (identity, provenance, time, quality rules) |

This contract **invents nothing**: no unit, timezone, mapping method or column is introduced that the inputs do not already state. Where the inputs are silent, the field says `not_established` or the item is listed in section 12.

## 2. Principles

1. **Measured, derived, simulated and synthetic are separate** record fields (`provenance`), never inferred from the database `origin` alone: the existing `origin` enum (`simulated`, `measured`, `replay`) is unchanged and cannot express `derived` or `synthetic`.
2. **Time is source text until a timezone is approved.** `ts_source_text` is the evidence; `ts_utc` is null while the timezone is undeclared, and the validator rejects a UTC value for v5.
3. **A value is either observed or absent.** Missing, not-reported and invalid are explicit states with a reason; nothing is imputed, clipped or averaged.
4. **Group power is never split per rack.** A group channel is returned as a group record or a pointer; no per-rack power field exists for it.
5. **Producers emit exactly the 1.0 key set** (all keys present, nulls explicit). Consumers must ignore unknown keys from later minor versions.

## 3. Telemetry record (`record_kind = "telemetry_record"`)

| Field | Type | Rule |
|---|---|---|
| `contract_version` | string | `1.x.y` or `1.x.y-draft` |
| `record_kind` | string | always `telemetry_record` |
| `facility_id` | string | TwinGrid Facility id as an opaque string; explicit, never defaulted |
| `site_status` | enum | `location_not_established` / `location_established` (v5: not established) |
| `dataset_id` | string or null | null for live/simulated; `danish-aau-v5` for the imported set |
| `stream_id` | string | `live` / `replay:<uuid>` / `import:<dataset_id>` (existing repo grammar); when `dataset_id` is set it must be `import:<dataset_id>` |
| `source_rack_id` | string or null | the source's rack number as text (`"1"`..`"6"`); null for group, room and facility scope |
| `source_server_id` | string or null | v5: always null |
| `source_server_status` | enum | `not_present_in_source` / `present` (`present` requires an id) |
| `asset_external_id`, `sensor_external_id` | string | Task 7 ids (v5 grammar enforced); `synthetic-example.` prefix only on fixtures |
| `mapping` | object or null | `mapping_id`, `mapping_version` (int >= 1), `method` (`csv_header_key` / `source_image_label` / `source_workbook_port_group`), `label_evidence` (`agent_transcribed` / `owner_verified` / `source_document` / `not_applicable`), `valid_time_status`, `applied_uniformly_over_window`; required for measured imports |
| `time_basis` | enum | `source_text_undeclared_tz` (needs `ts_source_text`, `ts_utc` null) / `utc_instant` (needs `ts_utc`) |
| `ts_source_text` | string or null | `YYYY-MM-DD HH:MM:SS`, calendar-valid, no timezone attached |
| `ts_utc` | string or null | RFC 3339 with `Z` or offset |
| `measurand` | string | `[a-z][a-z0-9_]*`; v5: `temperature`, `power`, `air_speed` |
| `unit` | string | v5: `degC`, `W`, `m/s`; use `not_established` where the source gives no unit |
| `value` | number or null | finite; null unless a source value exists |
| `value_text` | string or null | canonical decimal at the declared resolution; must parse to `value` exactly |
| `resolution_decimals` | int or null | v5: temperature 2, power 1, air speed null. Owner decisions at CK-1, **not sensor specifications** |
| `state` | enum | `observed` / `missing` / `invalid` / `not_reported` / `stale` (section 5) |
| `observed` | bool | equals "value is not null" |
| `quality` | enum or null | `ok` / `flagged` / `invalid`; null for missing and not_reported |
| `reason_code` | string or null | `[a-z][a-z0-9_]*`; required for flagged, missing, not_reported, invalid |
| `age_seconds` | number or null | only on `stale`, > 0 |
| `provenance` | enum | `measured` / `derived` / `simulated` / `synthetic` |
| `storage_class` | enum | `telemetry_sample` / `research_import_file` / `derived_series` / `fixture_only` |
| `origin_db` | enum or null | existing DB enum value if stored in `telemetry_sample`, else null |
| `attribution` | object | `scope` (`rack` / `rack_group` / `room` / `facility` / `unattributed`), `member_source_rack_ids` (unique, ascending), `split_allowed` (always false) |
| `source_ref` | object or null | `file`, `column`, `row_ordinal`, `row_numbering`, `ts_text`, `key`, `file_sha256` (section 8) |
| `ledger` | object or null | `row_disposition`, `group_size`, `group_ref` (section 8) |
| `derivation` | object or null | required exactly when `provenance = derived` (section 8) |
| `protocol_ref` | object or null | `{protocol_sha256}`; required for measured imports |
| `fixture` | bool | true for every example; a non-synthetic fixture carries no value |

## 4. Time

- v5 records: `time_basis = source_text_undeclared_tz`, `ts_utc = null`. Ordering and equality use the text; no offset is added or implied.
- History bounds in the API are **naive source text** (`from_source_text`, `to_source_text`), never UTC.
- To introduce UTC for v5 a protocol amendment must first document and approve the source timezone; this contract then adds nothing, only the validator profile changes.
- `stale` is a freshness concept for live/replay data with a UTC instant. It is never produced for imported history.

## 5. States

| State | `value` | `quality` | `reason_code` | `observed` | Meaning |
|---|---|---|---|---|---|
| `observed` | number | `ok` or `flagged` | forbidden if `ok`, required if `flagged` | true | a source value; out-of-range values are `flagged` and kept, never clipped |
| `missing` | null | null | required | false | the source reported a row but the cell is unusable (v5: `conflict_unresolved_tie`; 10,602 cells in the full file) |
| `not_reported` | null | null | required | false | the source has no row for that second |
| `invalid` | number or null | `invalid` | required | value present? | rejected by validation; kept for audit |
| `stale` | last value | `ok`/`flagged` | optional | true | live/replay only; `age_seconds > 0` |

## 6. Provenance and storage

| `provenance` | `storage_class` | `origin_db` | Notes |
|---|---|---|---|
| `measured` | `telemetry_sample` or `research_import_file` | `measured`/`replay`, or null for files | needs lineage (section 8) when imported |
| `derived` | `derived_series` only | null | never inserted into `telemetry_sample`; needs `derivation` |
| `simulated` | `telemetry_sample` | `simulated` | TwinGrid simulator output |
| `synthetic` | `fixture_only` | null | `fixture = true`, ids start with `synthetic-example.` |

## 7. Attribution and group power

- `rack`: exactly one member equal to `source_rack_id`. `rack_group`: two or more members, `source_rack_id` null. Other scopes: no rack.
- v5 power: Ch 1 = `rack_group` {1,2,3}, Ch 2 = `rack_group` {4,6} (never "4-6"), Ch 3 = `rack` {5} (`single_rack_port`). Any other membership is rejected (`E_V5_POWER_GROUP`).
- A derived value computed from a `rack_group` input stays `rack_group` (`E_GROUP_SPLIT`).
- Rack views of Racks 1-4 and 6 show a **group pointer** with `value = null` and `split_allowed = false`; only Rack 5 may show rack-level power.
- Temperature probes are never group-attributed.

## 8. Lineage

**`source_ref`**: `file`, `column` (neither contains `|`), `row_ordinal` (1-based integer or null), `row_numbering` (`data_row_ordinal_excluding_header` / `unspecified`), `ts_text` (equals `ts_source_text`), `key` = `file|column|ts_text`, `file_sha256` (64 hex or null). The base of `row_ordinal` is an open question (section 12).

**`ledger`** (per record): `row_disposition` in `retained`, `conflict_resolved_by_source_rule`, `conflict_cell_missing`, `flagged`; `group_size` >= 1; `group_ref`. A `conflict_unresolved_tie` record must be `missing` with `conflict_cell_missing` and `group_size >= 2`. Disposition `flagged` holds exactly when `quality = flagged`.

**Cleaning-ledger entry** (`record_kind = "ledger_entry"`, one per raw row): `dataset_id`, `file`, `row_ordinal`, `row_numbering`, `ts_source_text`, `disposition` (the six protocol dispositions), `reason_code`, `group_size`, `protocol_sha256`. `exact_duplicate` and `dropped_with_reason` rows exist only as ledger entries, never as telemetry records.

**`derivation`**: `formula_id`, `formula_text`, `inputs` (list of `{sensor_external_id, source_ref_key}`), `input_scopes` (one scope per input), `mapping_id`, `mapping_version`, `code_version`, `method_approval_ref`. No derived rack proxy exists for v5 and none is planned.

## 9. v5 profile (`dataset_id = danish-aau-v5`)

Sensor ids match `danish-aau-v5.(temperature.mod<M>.ch<C>|power.ch[1-3]|velocity.<N>)`; asset ids `danish-aau-v5.(rack.[1-6]|pdu.ch[1-3]|zone.serverroom)`; no server; naive source time; site not established; units and resolutions as in section 3; measured records cite the locked protocol hash; mappings are `not_established` in time and applied uniformly over the window (owner answer O-1); temperature rack association comes from `source_image_label`, power membership from `source_workbook_port_group`.

## 10. API response shapes

Every envelope carries `contract_version`, `kind`, `facility_id`, `dataset_id`, `stream_id`. Facility and stream are **explicit on every request**: no default, and never `live` for imported data. Route paths are illustrative and belong to Task 9.

| `kind` | Extra fields |
|---|---|
| `sensor_list` | `count`, `items[]` = `sensor_external_id`, `asset_external_id`, `measurand`, `unit`, `mapping_id`, `mapping_version`, `method`, `measurand_status` |
| `latest` | `sensor_external_id`, `measurand_status`, `window_status`, `record_absent_reason`, `record` (record or null) |
| `history` | `sensor_external_id`, `from_source_text`, `to_source_text`, `include_invalid`, `include_states`, `count`, `page` {`limit` 1-1000, `next_cursor`}, `records[]` strictly ascending by time |
| `rack_view` | `source_rack_id`, `asset_external_id`, `temperature_sensors[]` (`source_label`, `source_position_word`, `label_evidence`, `record`), `power` = `group_pointer` / `single_rack_port` / `not_available` |
| `error` | `status` (4xx/5xx), `code` (`unknown_facility`, `unknown_dataset`, `unknown_entity`, `stream_required`, `bad_request`, `internal`), `message` |

**Telling "no value" cases apart:** `measurand_status` (`sensor_present`, `no_sensor_for_asset`, `group_channel_only`) and `window_status` (`inside_dataset_window`, `outside_dataset_window`, `not_applicable`) on `latest`; an unknown entity is an `error` with `unknown_entity`; a `missing` or `not_reported` record is a state inside the window. `record_absent_reason` is required whenever `record` is null.

## 11. Examples (synthetic only)

Every shipped example uses the fixture namespace `synthetic-example`, year-2000 timestamps and patterned values, and carries `fixture = true`. One shape-only example uses real v5 ids with **no value** to exercise the v5 profile. Measured and derived shapes with numbers are tested by building twins inside the test suite, so no fake "measured" payload is ever shipped.

Observed temperature (record):
```json
{
  "age_seconds": null,
  "asset_external_id": "synthetic-example.rack.a",
  "attribution": {
    "member_source_rack_ids": [
      "1"
    ],
    "scope": "rack",
    "split_allowed": false
  },
  "contract_version": "1.0.0-draft",
  "dataset_id": "synthetic-example",
  "derivation": null,
  "facility_id": "synthetic-example-facility",
  "fixture": true,
  "ledger": {
    "group_ref": "synthetic_example_file.csv|2000-01-01 00:00:01",
    "group_size": 1,
    "row_disposition": "retained"
  },
  "mapping": {
    "applied_uniformly_over_window": true,
    "label_evidence": "not_applicable",
    "mapping_id": "synthetic-example-map-1",
    "mapping_version": 1,
    "method": "csv_header_key",
    "valid_time_status": "not_established"
  },
  "measurand": "temperature",
  "observed": true,
  "origin_db": null,
  "protocol_ref": {
    "protocol_sha256": "0ff4521697f81c397c81f1af5686284f505956cc239a67b6fe1605adc7b47098"
  },
  "provenance": "synthetic",
  "quality": "ok",
  "reason_code": null,
  "record_kind": "telemetry_record",
  "resolution_decimals": 2,
  "sensor_external_id": "synthetic-example.temperature.s1",
  "site_status": "location_not_established",
  "source_rack_id": "1",
  "source_ref": {
    "column": "Synthetic temperature 1",
    "file": "synthetic_example_file.csv",
    "file_sha256": null,
    "key": "synthetic_example_file.csv|Synthetic temperature 1|2000-01-01 00:00:01",
    "row_numbering": "data_row_ordinal_excluding_header",
    "row_ordinal": 1,
    "ts_text": "2000-01-01 00:00:01"
  },
  "source_server_id": null,
  "source_server_status": "not_present_in_source",
  "state": "observed",
  "storage_class": "fixture_only",
  "stream_id": "import:synthetic-example",
  "time_basis": "source_text_undeclared_tz",
  "ts_source_text": "2000-01-01 00:00:01",
  "ts_utc": null,
  "unit": "degC",
  "value": 20.12,
  "value_text": "20.12"
}
```
Group power channel (never per rack):
```json
{
  "age_seconds": null,
  "asset_external_id": "synthetic-example.pdu.ch1",
  "attribution": {
    "member_source_rack_ids": [
      "1",
      "2",
      "3"
    ],
    "scope": "rack_group",
    "split_allowed": false
  },
  "contract_version": "1.0.0-draft",
  "dataset_id": "synthetic-example",
  "derivation": null,
  "facility_id": "synthetic-example-facility",
  "fixture": true,
  "ledger": {
    "group_ref": "synthetic_example_file.csv|2000-01-01 00:00:01",
    "group_size": 1,
    "row_disposition": "retained"
  },
  "mapping": {
    "applied_uniformly_over_window": true,
    "label_evidence": "not_applicable",
    "mapping_id": "synthetic-example-map-1",
    "mapping_version": 1,
    "method": "csv_header_key",
    "valid_time_status": "not_established"
  },
  "measurand": "power",
  "observed": true,
  "origin_db": null,
  "protocol_ref": {
    "protocol_sha256": "0ff4521697f81c397c81f1af5686284f505956cc239a67b6fe1605adc7b47098"
  },
  "provenance": "synthetic",
  "quality": "ok",
  "reason_code": null,
  "record_kind": "telemetry_record",
  "resolution_decimals": 1,
  "sensor_external_id": "synthetic-example.power.ch1",
  "site_status": "location_not_established",
  "source_rack_id": null,
  "source_ref": {
    "column": "Synthetic power Ch 1 (W)",
    "file": "synthetic_example_file.csv",
    "file_sha256": null,
    "key": "synthetic_example_file.csv|Synthetic power Ch 1 (W)|2000-01-01 00:00:01",
    "row_numbering": "data_row_ordinal_excluding_header",
    "row_ordinal": 1,
    "ts_text": "2000-01-01 00:00:01"
  },
  "source_server_id": null,
  "source_server_status": "not_present_in_source",
  "state": "observed",
  "storage_class": "fixture_only",
  "stream_id": "import:synthetic-example",
  "time_basis": "source_text_undeclared_tz",
  "ts_source_text": "2000-01-01 00:00:01",
  "ts_utc": null,
  "unit": "W",
  "value": 300.0,
  "value_text": "300.0"
}
```
Conflict-tied cell (missing, not imputed):
```json
{
  "age_seconds": null,
  "asset_external_id": "synthetic-example.rack.a",
  "attribution": {
    "member_source_rack_ids": [
      "1"
    ],
    "scope": "rack",
    "split_allowed": false
  },
  "contract_version": "1.0.0-draft",
  "dataset_id": "synthetic-example",
  "derivation": null,
  "facility_id": "synthetic-example-facility",
  "fixture": true,
  "ledger": {
    "group_ref": "synthetic_example_file.csv|2000-01-01 00:00:03",
    "group_size": 2,
    "row_disposition": "conflict_cell_missing"
  },
  "mapping": {
    "applied_uniformly_over_window": true,
    "label_evidence": "not_applicable",
    "mapping_id": "synthetic-example-map-1",
    "mapping_version": 1,
    "method": "csv_header_key",
    "valid_time_status": "not_established"
  },
  "measurand": "temperature",
  "observed": false,
  "origin_db": null,
  "protocol_ref": {
    "protocol_sha256": "0ff4521697f81c397c81f1af5686284f505956cc239a67b6fe1605adc7b47098"
  },
  "provenance": "synthetic",
  "quality": null,
  "reason_code": "conflict_unresolved_tie",
  "record_kind": "telemetry_record",
  "resolution_decimals": 2,
  "sensor_external_id": "synthetic-example.temperature.s1",
  "site_status": "location_not_established",
  "source_rack_id": "1",
  "source_ref": {
    "column": "Synthetic temperature 1",
    "file": "synthetic_example_file.csv",
    "file_sha256": null,
    "key": "synthetic_example_file.csv|Synthetic temperature 1|2000-01-01 00:00:03",
    "row_numbering": "data_row_ordinal_excluding_header",
    "row_ordinal": 1,
    "ts_text": "2000-01-01 00:00:03"
  },
  "source_server_id": null,
  "source_server_status": "not_present_in_source",
  "state": "missing",
  "storage_class": "fixture_only",
  "stream_id": "import:synthetic-example",
  "time_basis": "source_text_undeclared_tz",
  "ts_source_text": "2000-01-01 00:00:03",
  "ts_utc": null,
  "unit": "degC",
  "value": null,
  "value_text": null
}
```
Rack view with a group pointer:
```json
{
  "asset_external_id": "synthetic-example.rack.a",
  "contract_version": "1.0.0-draft",
  "dataset_id": "synthetic-example",
  "facility_id": "synthetic-example-facility",
  "kind": "rack_view",
  "power": {
    "kind": "group_pointer",
    "member_source_rack_ids": [
      "1",
      "2",
      "3"
    ],
    "sensor_external_id": "synthetic-example.power.ch1",
    "split_allowed": false,
    "value": null
  },
  "source_rack_id": "1",
  "stream_id": "import:synthetic-example",
  "temperature_sensors": [
    {
      "label_evidence": "not_applicable",
      "record": {
        "age_seconds": null,
        "asset_external_id": "synthetic-example.rack.a",
        "attribution": {
          "member_source_rack_ids": [
            "1"
          ],
          "scope": "rack",
          "split_allowed": false
        },
        "contract_version": "1.0.0-draft",
        "dataset_id": "synthetic-example",
        "derivation": null,
        "facility_id": "synthetic-example-facility",
        "fixture": true,
        "ledger": {
          "group_ref": "synthetic_example_file.csv|2000-01-01 00:00:01",
          "group_size": 1,
          "row_disposition": "retained"
        },
        "mapping": {
          "applied_uniformly_over_window": true,
          "label_evidence": "not_applicable",
          "mapping_id": "synthetic-example-map-1",
          "mapping_version": 1,
          "method": "csv_header_key",
          "valid_time_status": "not_established"
        },
        "measurand": "temperature",
        "observed": true,
        "origin_db": null,
        "protocol_ref": {
          "protocol_sha256": "0ff4521697f81c397c81f1af5686284f505956cc239a67b6fe1605adc7b47098"
        },
        "provenance": "synthetic",
        "quality": "ok",
        "reason_code": null,
        "record_kind": "telemetry_record",
        "resolution_decimals": 2,
        "sensor_external_id": "synthetic-example.temperature.s1",
        "site_status": "location_not_established",
        "source_rack_id": "1",
        "source_ref": {
          "column": "Synthetic temperature 1",
          "file": "synthetic_example_file.csv",
          "file_sha256": null,
          "key": "synthetic_example_file.csv|Synthetic temperature 1|2000-01-01 00:00:01",
          "row_numbering": "data_row_ordinal_excluding_header",
          "row_ordinal": 1,
          "ts_text": "2000-01-01 00:00:01"
        },
        "source_server_id": null,
        "source_server_status": "not_present_in_source",
        "state": "observed",
        "storage_class": "fixture_only",
        "stream_id": "import:synthetic-example",
        "time_basis": "source_text_undeclared_tz",
        "ts_source_text": "2000-01-01 00:00:01",
        "ts_utc": null,
        "unit": "degC",
        "value": 20.12,
        "value_text": "20.12"
      },
      "sensor_external_id": "synthetic-example.temperature.s1",
      "source_label": "Synthetic rack a front",
      "source_position_word": "front"
    }
  ]
}
```

## 12. Interface to the repository and Task 9 (verified by reading the supplied repo copy; nothing executed)

These facts constrain **Task 9** and are why imported data is not yet writable:
1. `telemetry_sample.ts_event` is NOT NULL and timezone-aware (migration `20261004000000_t16_telemetry_sample`). Storing imported rows there would assert a UTC instant, which this contract refuses while the timezone is undeclared. **Task 9 blocker; needs an owner decision on timezone or a separate store.**
2. `quality` is limited to `ok` / `invalid` by a check constraint, and `invalid_reason` to `range` / `future`. Contract quality `flagged` and reason codes such as `conflict_unresolved_tie` cannot be stored in `telemetry_sample` as they are; `missing` cells need a separate missing-cell index.
3. The writer rejects naive timestamps by default (`naive_policy = "reject"`), takes batches of at most 1,000 and keeps the first write per (sensor, stream, `ts_event`); conflicts must be resolved before import, as the protocol already does.
4. `Sensor.source_tz` defaults to `UTC` (NOT NULL), so creating sensors through the current functions would silently assert a timezone.
5. The read route defaults `stream=live`, defaults `quality=ok` (hides invalid rows) and returns UTC with a `Z` suffix; it must not serve imported data unchanged. This contract requires explicit stream, explicit `include_invalid` and source-text bounds.
6. The `origin` enum is `simulated`, `measured`, `replay`. `derived` and `synthetic` have no origin value and must stay out of `telemetry_sample`.
7. The research harness has its own `Provenance` enum that includes `estimated` and omits `synthetic`; `estimated` is not a wire label here.

## 13. Versioning

Additive only within 1.x: new optional keys, new enum members on non-gating fields, new error codes. Removing or renaming a key, changing a rule's meaning or tightening an enum is 2.0. The version moves from `1.0.0-draft` to `1.0.0` when the owner approves; a producer must not emit a version it has not validated against.

## 14. How Tasks 11-17 use this

| Task | Uses |
|---|---|
| 11 reader | `source_ref`, `row_numbering`, ledger entries |
| 12 cleaning | states, `reason_code` catalogue (to be defined there), ledger dispositions |
| 13 mapping | ids, `mapping`, `attribution`, v5 profile |
| 15 import | record shape, storage matrix, the section 12 constraints |
| 16 API | the five envelopes and the explicit-stream rule |
| 17 frontend | states, `observed`, provenance labels, group pointer (show `Not reported` where `state = not_reported`) |

Each agent should run the examples and negative vectors against its own implementation: `negative_vectors.py` is language-neutral (path edits on the example files plus an expected error code).

## 15. Owner questions (draft defaults)

1. **Measurand name `air_speed`** (Task 7 sensor ids say `velocity`). Default: measurand `air_speed`, id segment unchanged.
2. **Cell state for a `dropped_with_reason` raw row**: the locked protocol is silent. Default: no record is emitted, the ledger entry carries the reason.
3. **Reason-code catalogue** (flag and drop reasons): defined in Task 12; the contract only requires the pattern `[a-z][a-z0-9_]*`.
4. **`row_ordinal` base**: 1-based data-row ordinal excluding the header; confirm against the Task 6 runner and Task 11.
5. **JSON Schema export**: the validator is Python only. A schema for the TypeScript frontend can be generated in Task 9 or 16 if wanted; it was not produced here because no schema library was available to test it.
