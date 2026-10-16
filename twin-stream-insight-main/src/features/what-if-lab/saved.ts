/** Task 15: saved scenarios and CSV export. PURE (storage access lives in `useSavedScenarios`). */
import { modeLabel, normalise, type LabInputs } from "./model";
import { csvCell } from "../reports-export/exportTable";
import { ESTIMATE_LABEL, METRICS, type MetricId, type MetricValues } from "./metrics";

export const MAX_SAVED = 8;
export const MAX_NAME = 40;
export const STORAGE_KEY = "twingrid.whatif.saved.v1";

export interface Snapshot {
  readonly inputs: LabInputs;
  readonly metrics: MetricValues;
  /** The backend's flag at the time: false = carbon uses the fallback intensity. */
  readonly carbonIsReal: boolean;
}
export interface SavedScenario extends Snapshot {
  readonly id: string;
  readonly name: string;
}

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** One stored record, or null when it is not a well-formed snapshot (a damaged or hand-edited entry is dropped, never repaired). */
export function parseSaved(raw: unknown): SavedScenario | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.id !== "string" || r.id === "" || typeof r.name !== "string" || r.name.trim() === "" || typeof r.carbonIsReal !== "boolean") return null;
  const i = r.inputs as Record<string, unknown> | null;
  const m = r.metrics as Record<string, unknown> | null;
  if (!i || typeof i !== "object" || !m || typeof m !== "object") return null;
  if (!isNum(i.itLoadPct) || !isNum(i.ambientC) || !isNum(i.setpointC) || typeof i.mode !== "string") return null;
  if (!METRICS.every((x) => isNum(m[x.id]))) return null;
  const inputs = normalise(i as Partial<LabInputs>);
  const metrics = Object.fromEntries(METRICS.map((x) => [x.id, m[x.id] as number])) as MetricValues;
  return { id: r.id, name: r.name.trim().slice(0, MAX_NAME), inputs, metrics, carbonIsReal: r.carbonIsReal };
}

export function parseSavedList(text: string | null): SavedScenario[] {
  if (!text) return [];
  try {
    const raw: unknown = JSON.parse(text);
    if (!Array.isArray(raw)) return [];
    return raw.map(parseSaved).filter((s): s is SavedScenario => s !== null).slice(0, MAX_SAVED);
  } catch {
    return [];
  }
}

export const serializeSaved = (list: readonly SavedScenario[]): string => JSON.stringify(list);

export type AddResult = { ok: true; list: SavedScenario[] } | { ok: false; reason: "full" | "empty-name" };

/** Append a snapshot. A duplicate name gets " (2)", " (3)" ... so names stay distinguishable in the compare table. */
export function addSaved(list: readonly SavedScenario[], name: string, snap: Snapshot, newId: () => string): AddResult {
  const base = name.trim().slice(0, MAX_NAME);
  if (base === "") return { ok: false, reason: "empty-name" };
  if (list.length >= MAX_SAVED) return { ok: false, reason: "full" };
  let unique = base;
  for (let n = 2; list.some((s) => s.name === unique); n += 1) unique = `${base.slice(0, MAX_NAME - 4)} (${n})`;
  return { ok: true, list: [...list, { id: newId(), name: unique, ...snap }] };
}

export const removeSaved = (list: readonly SavedScenario[], id: string): SavedScenario[] => list.filter((s) => s.id !== id);

// ---------------------------------------------------------------------------------------------------- CSV
/** A spreadsheet would run a cell that starts with = + - @ (or a tab/CR) as a formula: prefix such TEXT with an apostrophe. Numbers are never prefixed. */
export { csvCell };

export interface CsvRow {
  readonly name: string;
  readonly kind: "baseline" | "current" | "saved";
  readonly snap: Snapshot;
}

export const CSV_HEADER = [
  "scenario", "kind", "it_load_pct", "ambient_C", "chilled_water_setpoint_C", "cooling_mode",
  ...METRICS.map((m) => `${m.id}${m.unit ? `_${m.unit.replace("°", "")}` : ""}`),
  "carbon_data_is_real", "label",
] as const;

export function toCsv(rows: readonly CsvRow[]): string {
  const lines = [CSV_HEADER.map(csvCell).join(",")];
  for (const r of rows) {
    const cells: (string | number | boolean)[] = [
      r.name, r.kind, r.snap.inputs.itLoadPct, r.snap.inputs.ambientC, r.snap.inputs.setpointC, r.snap.inputs.mode,
      ...METRICS.map((m) => r.snap.metrics[m.id as MetricId]),
      r.snap.carbonIsReal, ESTIMATE_LABEL,
    ];
    lines.push(cells.map(csvCell).join(","));
  }
  return `${lines.join("\r\n")}\r\n`;
}

export const defaultSaveName = (i: LabInputs): string => `${i.itLoadPct}% · ${i.ambientC} °C · ${i.setpointC} °C · ${modeLabel(i.mode)}`;
