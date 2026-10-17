/**
 * Task 28: pure view-model for asset health and work orders. No React, no network, no clock.
 *
 * Health is a rule-based indicator on SIMULATED data, not a failure prediction, and there is no remaining-life estimate
 * (the backend says so in `remaining_life`). A work order is a record: nothing is dispatched. The server is the judge of
 * every rule here (roles, status flow, existence of the alert or asset); this file only builds requests and wording.
 */
import type { HealthAsset, HealthSensor, WorkOrder } from "./schema";

export const HEALTH_LABEL = "Rule-based indicator on simulated data; not a failure prediction.";
export const MAX_TITLE = 160;
export const MAX_DESCRIPTION = 2000;
export const MAX_ASSIGNEE = 64;
export const MAX_NOTE = 500;

/** Colour is never the only cue. */
export const HEALTH_CUE = {
  ok: { glyph: "●", word: "ok" },
  watch: { glyph: "▲", word: "watch" },
  warning: { glyph: "■", word: "warning" },
  no_data: { glyph: "?", word: "not measured" },
} as const;
export type HealthStatus = keyof typeof HEALTH_CUE;

export const ORDER_STATUS_LABEL = { open: "Open", in_progress: "In progress", done: "Done", cancelled: "Cancelled" } as const;
export const ACTION_LABEL = { open: "Re-open", in_progress: "Start work", done: "Mark done", cancelled: "Cancel order" } as const;
export const PRIORITY_LABEL = { low: "Low", medium: "Medium", high: "High" } as const;

/** A row can raise a work order only when its status asks for attention. */
export const needsAttention = (s: HealthStatus): boolean => s === "watch" || s === "warning";

const SEVERITY: Record<HealthStatus, number> = { no_data: 0, ok: 1, watch: 2, warning: 3 };

/** The sensor that makes an asset's status what it is (the worst one), for a prefilled work order. */
export function worstSensor(asset: HealthAsset): HealthSensor | null {
  let worst: HealthSensor | null = null;
  for (const s of asset.sensors) if (s.status !== "no_data" && (!worst || SEVERITY[s.status] > SEVERITY[worst.status])) worst = s;
  return worst;
}

const num = (v: number, digits = 1) => (Number.isFinite(v) ? v.toFixed(digits) : "n/a");

/** One plain sentence about a sensor's trend; says "not enough data" rather than inventing one. */
export function trendText(s: HealthSensor): string {
  const t = s.trend;
  if (!t) return "Trend: not enough valid samples (NOT MEASURED).";
  const hours = num(t.span_hours);
  if (t.direction === "flat") return `Trend: flat over ${hours} h.`;
  const range = t.drift_pct_of_range === null ? "" : ` (${num(t.drift_pct_of_range, 0)}% of the valid range)`;
  return `Trend: ${t.direction} ${num(Math.abs(t.change_over_window))} ${s.unit} over ${hours} h${range}.`;
}

export function latestText(s: HealthSensor): string {
  return s.latest ? `${num(s.latest.value)} ${s.unit}` : "no valid value";
}

// ------------------------------------------------------------------------------------------------ create form

export type SourceKind = "manual" | "alert" | "health";
export interface CreateForm {
  sourceKind: SourceKind;
  title: string;
  description: string;
  priority: "low" | "medium" | "high";
  assignee: string;
  alertId: string;
  assetExternalId: string;
  measurand: string;
}
export const EMPTY_FORM: CreateForm = {
  sourceKind: "manual",
  title: "",
  description: "",
  priority: "medium",
  assignee: "",
  alertId: "",
  assetExternalId: "",
  measurand: "",
};
export type FormErrors = Partial<Record<"title" | "description" | "assignee" | "alertId" | "assetExternalId", string>>;

export interface CreateBody {
  title?: string;
  description?: string;
  priority: "low" | "medium" | "high";
  assignee?: string;
  asset_external_id?: string;
  source: { kind: SourceKind; alert_id?: number; measurand?: string };
}

/** Validate what was typed (nothing is clamped or cut) and build the request body. Empty optional fields are left out. */
export function parseCreate(f: CreateForm): { ok: true; body: CreateBody } | { ok: false; errors: FormErrors } {
  const errors: FormErrors = {};
  const title = f.title.trim();
  const description = f.description.trim();
  const assignee = f.assignee.trim();
  if (f.sourceKind === "manual" && !title) errors.title = "Enter a title.";
  if (title.length > MAX_TITLE) errors.title = `The title is at most ${MAX_TITLE} characters.`;
  if (description.length > MAX_DESCRIPTION) errors.description = `The description is at most ${MAX_DESCRIPTION} characters.`;
  if (assignee.length > MAX_ASSIGNEE) errors.assignee = `The assignee is at most ${MAX_ASSIGNEE} characters.`;
  const alertId = /^\d+$/.test(f.alertId.trim()) ? Number(f.alertId.trim()) : NaN;
  if (f.sourceKind === "alert" && !(Number.isInteger(alertId) && alertId >= 1)) errors.alertId = "Choose an alert.";
  if (f.sourceKind === "health" && !f.assetExternalId.trim()) errors.assetExternalId = "Choose an asset.";
  if (Object.keys(errors).length) return { ok: false, errors };

  const source: CreateBody["source"] = { kind: f.sourceKind };
  if (f.sourceKind === "alert") source.alert_id = alertId;
  if (f.sourceKind === "health" && f.measurand.trim()) source.measurand = f.measurand.trim();
  const body: CreateBody = { priority: f.priority, source };
  if (title) body.title = title;
  if (description) body.description = description;
  if (assignee) body.assignee = assignee;
  if (f.assetExternalId.trim() && f.sourceKind !== "manual") body.asset_external_id = f.assetExternalId.trim();
  return { ok: true, body };
}

/** The form for "create a work order from this health row": the asset and its worst sensor, priority from the status. */
export function formFromHealth(asset: HealthAsset): CreateForm {
  return {
    ...EMPTY_FORM,
    sourceKind: "health",
    assetExternalId: asset.external_id,
    measurand: worstSensor(asset)?.measurand ?? "",
    priority: asset.status === "warning" ? "high" : "medium",
  };
}

export const formFromAlert = (alertId: number): CreateForm => ({ ...EMPTY_FORM, sourceKind: "alert", alertId: String(alertId) });

/** "Simulated" / "manual" as shown next to an order: the data that raised it, never a measurement. */
export const originText = (o: Pick<WorkOrder, "origin" | "source_kind">): string =>
  o.origin === "simulated" ? `from simulated ${o.source_kind === "alert" ? "alert" : "health data"}` : "entered by hand";
