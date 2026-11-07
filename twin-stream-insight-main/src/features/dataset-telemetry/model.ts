/**
 * Task 17: pure view model for one imported-dataset record. Dataset values have their own labels (G1-D8) because the
 * shared provenance badge classifies by origin_db, which is null for file-backed imports.
 *
 * Rules enforced here (contract section 5, Task 9 section 8): a record that has no value is never rendered as a number;
 * "not_reported" reads "Not reported"; nothing is ever filled from a facility reading, another rack, or an earlier value;
 * imported history is never described as live; source time is shown as text with the timezone stated as not established.
 */
import type { RackPower, TelemetryRecord } from "./schemas";

export const NOT_REPORTED_TEXT = "Not reported";

export type ReadoutKind = "value" | "not_reported" | "missing" | "invalid" | "absent";

export interface Readout {
  kind: ReadoutKind;
  /** Display text for the value cell. Never a number unless the record carries one. */
  valueText: string;
  unit: string | null;
  /** Human sentence explaining a non-value state; null when a value is shown without caveat. */
  note: string | null;
  quality: "ok" | "flagged" | "invalid" | null;
  provenanceLabel: string;
  timeText: string | null;
  /** "Recorded dataset (historical), not live" for import streams. */
  modeLabel: string;
  lineage: string | null;
}

export const PROVENANCE_LABEL: Record<TelemetryRecord["provenance"], string> = {
  measured: "Measured",
  derived: "Derived",
  simulated: "Simulated",
  synthetic: "Synthetic example",
};

const REASON_TEXT: Record<string, string> = {
  conflict_unresolved_tie: "The source reported conflicting values for this second and no documented rule chooses between them, so the cell is left empty.",
  not_reported_at_time: "The source has no row for this second.",
  outside_dataset_window: "This time is outside the recorded dataset window.",
  no_sensor_for_asset: "The source has no sensor of this kind for this asset.",
  group_channel_only: "The source measures this only as a group channel.",
};

export function reasonText(code: string | null): string | null {
  if (code === null) return null;
  return REASON_TEXT[code] ?? `Reason: ${code.replace(/_/g, " ")}`;
}

export function modeLabel(streamId: string): string {
  if (streamId.startsWith("import:")) return "Recorded dataset (historical), not live";
  if (streamId === "live") return "Live";
  return "Replay";
}

export function timeText(r: Pick<TelemetryRecord, "time_basis" | "ts_source_text" | "ts_utc">): string | null {
  if (r.time_basis === "source_text_undeclared_tz") {
    return r.ts_source_text === null ? null : `${r.ts_source_text} (source time, timezone not established)`;
  }
  return r.ts_utc;
}

export function lineageText(r: TelemetryRecord): string | null {
  const ref = r.source_ref;
  if (!ref) return null;
  const row = ref.row_ordinal === null ? "row unspecified" : `data row ${ref.row_ordinal}`;
  return `${ref.file} · ${ref.column} · ${row}`;
}

export function toReadout(r: TelemetryRecord | null, absentReason?: string): Readout {
  if (r === null) {
    return {
      kind: "absent",
      valueText: NOT_REPORTED_TEXT,
      unit: null,
      note: reasonText(absentReason ?? "not_reported_at_time"),
      quality: null,
      provenanceLabel: "No record",
      timeText: null,
      modeLabel: "Recorded dataset (historical), not live",
      lineage: null,
    };
  }
  const base = {
    unit: r.unit,
    quality: r.quality,
    provenanceLabel: PROVENANCE_LABEL[r.provenance],
    timeText: timeText(r),
    modeLabel: modeLabel(r.stream_id),
    lineage: lineageText(r),
  };
  if (r.state === "not_reported") {
    return { ...base, kind: "not_reported", valueText: NOT_REPORTED_TEXT, unit: null, note: reasonText(r.reason_code) };
  }
  if (r.state === "missing") {
    return { ...base, kind: "missing", valueText: "No value", unit: null, note: reasonText(r.reason_code) };
  }
  // observed / stale / invalid: only ever show the record's own canonical text.
  const text = r.value_text ?? (r.value === null ? null : String(r.value));
  if (r.state === "invalid" || text === null) {
    return { ...base, kind: "invalid", valueText: text ?? "No value", note: reasonText(r.reason_code) ?? "Rejected by validation; kept for audit." };
  }
  const note = r.quality === "flagged" ? (reasonText(r.reason_code) ?? "Flagged by validation; value kept as recorded.") : null;
  return { ...base, kind: "value", valueText: text, note };
}

export interface PowerReadout {
  kind: "group_pointer" | "single_rack_port" | "not_available";
  title: string;
  detail: string;
  readout: Readout | null;
}

export function toPowerReadout(p: RackPower, sourceRackId: string): PowerReadout {
  if (p.kind === "group_pointer") {
    return {
      kind: "group_pointer",
      title: "Power: group channel only",
      detail: `The source measures power for racks ${p.member_source_rack_ids.join(", ")} together on ${p.sensor_external_id}. It is not split per rack, so rack ${sourceRackId} has no rack-level power value.`,
      readout: null,
    };
  }
  if (p.kind === "single_rack_port") {
    return { kind: "single_rack_port", title: "Power", detail: `Single-rack port ${p.record.sensor_external_id}.`, readout: toReadout(p.record) };
  }
  return { kind: "not_available", title: "Power", detail: "No power channel is available for this rack.", readout: null };
}
