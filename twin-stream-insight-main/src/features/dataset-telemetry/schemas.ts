/**
 * Task 17: zod schemas for the Task 8 telemetry contract (twingrid.rack_telemetry 1.x), reduced to what the readout
 * needs but strict about every enum. No default / catch / coerce: a bad payload fails loudly instead of rendering a
 * guessed value. Owned by this feature; nothing under src/contract or src/provenance is touched (G1-D8).
 */
import { z } from "zod";

export const PROVENANCE = ["measured", "derived", "simulated", "synthetic"] as const;
export const STATES = ["observed", "missing", "invalid", "not_reported", "stale"] as const;
export const QUALITY = ["ok", "flagged", "invalid"] as const;
export const TIME_BASIS = ["source_text_undeclared_tz", "utc_instant"] as const;
export const SCOPES = ["rack", "rack_group", "room", "facility", "unattributed"] as const;
export const LABEL_EVIDENCE = ["agent_transcribed", "owner_verified", "source_document", "not_applicable"] as const;

const versionString = z.string().regex(/^1\.\d+\.\d+(-draft)?$/);
const streamId = z.string().regex(/^(live|replay:[0-9a-f-]{36}|import:[a-z0-9.-]{1,57})$/);

const sourceRef = z
  .object({
    file: z.string(),
    column: z.string(),
    row_ordinal: z.number().int().nullable(),
    row_numbering: z.enum(["data_row_ordinal_excluding_header", "unspecified"]),
    ts_text: z.string(),
    key: z.string(),
    file_sha256: z.string().nullable(),
  })
  .passthrough();

const mapping = z
  .object({
    mapping_id: z.string(),
    mapping_version: z.number().int().min(1),
    method: z.enum(["csv_header_key", "source_image_label", "source_workbook_port_group"]),
    label_evidence: z.enum(LABEL_EVIDENCE),
  })
  .passthrough();

const attribution = z
  .object({
    scope: z.enum(SCOPES),
    member_source_rack_ids: z.array(z.string()),
    split_allowed: z.literal(false),
  })
  .passthrough();

const derivation = z
  .object({ formula_id: z.string(), formula_text: z.string() })
  .passthrough();

export const telemetryRecordSchema = z
  .object({
    contract_version: versionString,
    record_kind: z.literal("telemetry_record"),
    facility_id: z.string().min(1),
    site_status: z.enum(["location_not_established", "location_established"]),
    dataset_id: z.string().nullable(),
    stream_id: streamId,
    source_rack_id: z.string().nullable(),
    source_server_id: z.string().nullable(),
    source_server_status: z.enum(["not_present_in_source", "present"]),
    asset_external_id: z.string().min(1),
    sensor_external_id: z.string().min(1),
    mapping: mapping.nullable(),
    time_basis: z.enum(TIME_BASIS),
    ts_source_text: z.string().nullable(),
    ts_utc: z.string().nullable(),
    measurand: z.string(),
    unit: z.string().min(1),
    value: z.number().finite().nullable(),
    value_text: z.string().nullable(),
    resolution_decimals: z.number().int().nullable(),
    state: z.enum(STATES),
    observed: z.boolean(),
    quality: z.enum(QUALITY).nullable(),
    reason_code: z.string().nullable(),
    age_seconds: z.number().nullable(),
    provenance: z.enum(PROVENANCE),
    storage_class: z.enum(["telemetry_sample", "research_import_file", "derived_series", "fixture_only"]),
    origin_db: z.enum(["measured", "simulated", "replay"]).nullable(),
    attribution,
    source_ref: sourceRef.nullable(),
    ledger: z.object({ row_disposition: z.string(), group_size: z.number().int().min(1), group_ref: z.string() }).passthrough().nullable(),
    derivation: derivation.nullable(),
    protocol_ref: z.object({ protocol_sha256: z.string() }).passthrough().nullable(),
    fixture: z.boolean(),
  })
  .passthrough();
export type TelemetryRecord = z.infer<typeof telemetryRecordSchema>;

const power = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("group_pointer"),
    sensor_external_id: z.string(),
    member_source_rack_ids: z.array(z.string()).min(2),
    split_allowed: z.literal(false),
    value: z.null(),
  }),
  z.object({ kind: z.literal("single_rack_port"), record: telemetryRecordSchema }).passthrough(),
  z.object({ kind: z.literal("not_available"), reason: z.string().optional() }).passthrough(),
]);
export type RackPower = z.infer<typeof power>;

export const rackViewEnvelopeSchema = z.object({
  contract_version: versionString,
  kind: z.literal("rack_view"),
  facility_id: z.string().min(1),
  dataset_id: z.string().min(1),
  stream_id: streamId,
  source_rack_id: z.string().min(1),
  asset_external_id: z.string().min(1),
  temperature_sensors: z.array(
    z.object({
      sensor_external_id: z.string(),
      source_label: z.string().nullable(),
      source_position_word: z.string().nullable(),
      label_evidence: z.enum(LABEL_EVIDENCE),
      record: telemetryRecordSchema.nullable(),
      record_absent_reason: z.string().optional(),
    })
  ),
  power,
});
export type RackViewEnvelope = z.infer<typeof rackViewEnvelopeSchema>;

export const errorEnvelopeSchema = z.object({
  contract_version: versionString,
  kind: z.literal("error"),
  status: z.number().int(),
  code: z.enum(["unknown_facility", "unknown_dataset", "unknown_entity", "stream_required", "bad_request", "internal"]),
  message: z.string(),
});
export type ErrorEnvelope = z.infer<typeof errorEnvelopeSchema>;

/** GET /api/datasets/{dataset_id}: only the fields the readout uses; everything else is passed through untouched. */
export const datasetRecordSchema = z
  .object({
    contract_version: versionString,
    kind: z.literal("dataset_record"),
    dataset_id: z.string().min(1),
    stream_id: streamId,
    attribution_text: z.string().nullable(),
    modifications_statement: z.string().nullable(),
    window: z.object({ first_source_text: z.string().nullable(), last_source_text: z.string().nullable() }).passthrough(),
    racks: z.array(z.object({ source_rack_id: z.string().min(1), asset_external_id: z.string(), name: z.string().nullable().optional() }).passthrough()),
  })
  .passthrough();
export type DatasetRecord = z.infer<typeof datasetRecordSchema>;
