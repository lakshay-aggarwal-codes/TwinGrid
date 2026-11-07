/**
 * Task 17: SYNTHETIC mock of the Task 8 contract, used until Task 16 freezes real routes. Every id starts with
 * "synthetic-example." and every record is provenance "synthetic" with fixture = true. The values are deliberately
 * different per rack so a test can prove a selected rack shows its own record and nothing is broadcast.
 */
import type { RackPower, RackViewEnvelope, TelemetryRecord } from "./schemas";

const PROTOCOL = "0ff4521697f81c397c81f1af5686284f505956cc239a67b6fe1605adc7b47098";

interface RecOpts {
  rack: string;
  asset: string;
  sensor: string;
  measurand: string;
  unit: string;
  ts: string;
  state?: TelemetryRecord["state"];
  value?: number | null;
  valueText?: string | null;
  quality?: TelemetryRecord["quality"];
  reason?: string | null;
  scope?: TelemetryRecord["attribution"]["scope"];
  members?: string[];
}

function rec(o: RecOpts): TelemetryRecord {
  const state = o.state ?? "observed";
  const hasValue = state === "observed" || state === "invalid";
  const value = hasValue ? (o.value ?? null) : null;
  return {
    contract_version: "1.1.0",
    record_kind: "telemetry_record",
    facility_id: "synthetic-example-facility",
    site_status: "location_not_established",
    dataset_id: "synthetic-example",
    stream_id: "import:synthetic-example",
    source_rack_id: o.scope === "rack_group" ? null : o.rack,
    source_server_id: null,
    source_server_status: "not_present_in_source",
    asset_external_id: o.asset,
    sensor_external_id: o.sensor,
    mapping: { mapping_id: "synthetic-example-map-1", mapping_version: 1, method: "csv_header_key", label_evidence: "not_applicable" },
    time_basis: "source_text_undeclared_tz",
    ts_source_text: o.ts,
    ts_utc: null,
    measurand: o.measurand,
    unit: o.unit,
    value,
    value_text: hasValue ? (o.valueText ?? (value === null ? null : String(value))) : null,
    resolution_decimals: o.measurand === "temperature" ? 2 : 1,
    state,
    observed: value !== null,
    quality: state === "observed" || state === "invalid" ? (o.quality ?? "ok") : null,
    reason_code: o.reason ?? null,
    age_seconds: null,
    provenance: "synthetic",
    storage_class: "fixture_only",
    origin_db: null,
    attribution: { scope: o.scope ?? "rack", member_source_rack_ids: o.members ?? [o.rack], split_allowed: false },
    source_ref: {
      file: "synthetic_example_file.csv",
      column: o.sensor,
      row_ordinal: 1,
      row_numbering: "data_row_ordinal_excluding_header",
      ts_text: o.ts,
      key: `synthetic_example_file.csv|${o.sensor}|${o.ts}`,
      file_sha256: null,
    },
    ledger: { row_disposition: "retained", group_size: 1, group_ref: `synthetic_example_file.csv|${o.ts}` },
    derivation: null,
    protocol_ref: { protocol_sha256: PROTOCOL },
    fixture: true,
  };
}

const TS = "2000-01-01 00:00:01";

function envelope(rack: string, asset: string, probes: RackViewEnvelope["temperature_sensors"], power: RackPower): RackViewEnvelope {
  return {
    contract_version: "1.1.0",
    kind: "rack_view",
    facility_id: "synthetic-example-facility",
    dataset_id: "synthetic-example",
    stream_id: "import:synthetic-example",
    source_rack_id: rack,
    asset_external_id: asset,
    temperature_sensors: probes,
    power,
  };
}

const probe = (rack: string, n: number, label: string, word: string, record: TelemetryRecord | null, absent?: string) => ({
  sensor_external_id: `synthetic-example.temperature.${rack}${n}`,
  source_label: label,
  source_position_word: word,
  label_evidence: "not_applicable" as const,
  record,
  ...(absent ? { record_absent_reason: absent } : {}),
});

const temp = (rack: string, asset: string, n: number, value: number, text: string, extra: Partial<RecOpts> = {}) =>
  rec({ rack, asset, sensor: `synthetic-example.temperature.${rack}${n}`, measurand: "temperature", unit: "degC", ts: TS, value, valueText: text, ...extra });

const noValue = (rack: string, asset: string, n: number, state: "missing" | "not_reported", reason: string) =>
  rec({ rack, asset, sensor: `synthetic-example.temperature.${rack}${n}`, measurand: "temperature", unit: "degC", ts: TS, state, reason });

const A = "synthetic-example.rack.a";
const B = "synthetic-example.rack.b";
const E = "synthetic-example.rack.e";
const groupPower: RackPower = {
  kind: "group_pointer",
  sensor_external_id: "synthetic-example.power.ch1",
  member_source_rack_ids: ["1", "2", "3"],
  split_allowed: false,
  value: null,
};

export const FIXTURE_RACKS: readonly RackViewEnvelope[] = [
  envelope(
    "1",
    A,
    [probe("1", 1, "Synthetic rack a front", "front", temp("1", A, 1, 20.12, "20.12")), probe("1", 2, "Synthetic rack a back", "back", temp("1", A, 2, 27.9, "27.90"))],
    groupPower
  ),
  envelope(
    "2",
    B,
    [
      probe("2", 1, "Synthetic rack b front", "front", temp("2", B, 1, 23.47, "23.47", { quality: "flagged", reason: "out_of_range" })),
      probe("2", 2, "Synthetic rack b back", "back", noValue("2", B, 2, "missing", "conflict_unresolved_tie")),
      probe("2", 3, "Synthetic rack b top", "top", null, "not_reported_at_time"),
    ],
    groupPower
  ),
  envelope("5", E, [probe("5", 1, "Synthetic rack e front", "front", noValue("5", E, 1, "not_reported", "not_reported_at_time"))], {
    kind: "single_rack_port",
    record: rec({ rack: "5", asset: E, sensor: "synthetic-example.power.ch3", measurand: "power", unit: "W", ts: TS, value: 812.5, valueText: "812.5" }),
  }),
];
