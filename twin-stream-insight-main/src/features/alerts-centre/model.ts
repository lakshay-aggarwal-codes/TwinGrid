/**
 * Task 17: the alerts centre's data model and pure helpers (no React, no network).
 *
 * Alerts come from `GET /api/alerts/inbox`. Lifecycle (open -> acknowledged -> resolved) is decided by the backend;
 * `nextStatuses` only mirrors its table so the UI offers the moves the server will accept. The server stays the judge.
 */
import { z } from "zod";
import { formatInstantParam } from "../replay/url";

export const STATUSES = ["open", "acknowledged", "resolved"] as const;
export type AlertStatus = (typeof STATUSES)[number];

export const SEVERITIES = ["CRITICAL", "WARNING", "INFO"] as const;
export type Severity = (typeof SEVERITIES)[number];

export const MAX_NOTE_CHARS = 1000;
export const MAX_ASSIGNEE_CHARS = 64;
/** The inbox request size (the backend maximum). Filters apply to these rows in the browser, so they cost no request. */
export const INBOX_LIMIT = 200;
/** One bulk acknowledge handles at most this many alerts, one request each, so it stays inside the backend's rate limit. */
export const BULK_MAX = 25;

export const InboxAlertSchema = z
  .object({
    id: z.number(),
    created_at: z.string().nullable(),
    type: z.string(),
    message: z.string(),
    severity: z.string(),
    score: z.number(),
    origin: z.string().nullable().optional(),
    model_version: z.string().nullable().optional(),
    acknowledged: z.boolean(),
    acknowledged_by: z.string().nullable(),
    acknowledged_at: z.string().nullable(),
    status: z.enum(STATUSES),
    assignee: z.string().nullable(),
    resolved_by: z.string().nullable(),
    resolved_at: z.string().nullable(),
  })
  .passthrough();
export type InboxAlert = z.output<typeof InboxAlertSchema>;
export const InboxSchema = z.array(InboxAlertSchema);

export const TimelineSchema = z.object({
  alert_id: z.number(),
  entries: z.array(
    z.object({
      at: z.string().nullable(),
      kind: z.string(),
      actor: z.string().nullable(),
      summary: z.string(),
      note: z.string().nullable(),
    }),
  ),
});
export type Timeline = z.output<typeof TimelineSchema>;

/** The body of `PATCH /api/alerts/{id}`: `assignee: null` clears it; an absent key leaves it alone. */
export interface AlertPatch {
  status?: AlertStatus;
  assignee?: string | null;
  note?: string;
}

// ------------------------------------------------------------------------------------------------ lifecycle

const NEXT: Record<AlertStatus, readonly AlertStatus[]> = {
  open: ["acknowledged", "resolved"],
  acknowledged: ["open", "resolved"],
  resolved: ["open"],
};

export function nextStatuses(status: AlertStatus): readonly AlertStatus[] {
  return NEXT[status];
}

export const ACTION_LABEL: Record<AlertStatus, string> = { open: "Re-open", acknowledged: "Acknowledge", resolved: "Resolve" };
export const STATUS_LABEL: Record<AlertStatus, string> = { open: "Open", acknowledged: "Acknowledged", resolved: "Resolved" };

/** The backend's severity, or "UNKNOWN" for a value this client does not know (shown as received elsewhere, never relabelled). */
export function severityOf(raw: string): Severity | "UNKNOWN" {
  return (SEVERITIES as readonly string[]).includes(raw) ? (raw as Severity) : "UNKNOWN";
}

// ------------------------------------------------------------------------------------------------ filters

export interface Filters {
  /** Empty = every severity. */
  severities: readonly Severity[];
  /** Empty = every status. */
  statuses: readonly AlertStatus[];
}
export const NO_FILTERS: Filters = { severities: [], statuses: [] };

export function applyFilters(alerts: readonly InboxAlert[], f: Filters): InboxAlert[] {
  return alerts.filter(
    (a) =>
      (f.severities.length === 0 || (f.severities as readonly string[]).includes(a.severity)) &&
      (f.statuses.length === 0 || f.statuses.includes(a.status)),
  );
}

export function toggleIn<T>(list: readonly T[], value: T): T[] {
  return list.includes(value) ? list.filter((x) => x !== value) : [...list, value];
}

export interface Counts {
  total: number;
  open: number;
  acknowledged: number;
  resolved: number;
  /** Critical alerts that are still open (not acknowledged, not resolved). */
  openCritical: number;
}
export function countAlerts(alerts: readonly InboxAlert[]): Counts {
  const c: Counts = { total: alerts.length, open: 0, acknowledged: 0, resolved: 0, openCritical: 0 };
  for (const a of alerts) {
    c[a.status] += 1;
    if (a.status === "open" && a.severity === "CRITICAL") c.openCritical += 1;
  }
  return c;
}

// ------------------------------------------------------------------------------------------------ selection and bulk

export function toggleSelected(selected: ReadonlySet<number>, id: number): Set<number> {
  const next = new Set(selected);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

/** Ids of the open alerts among `visible`, newest first, capped at BULK_MAX (what "Select all open" picks). */
export function selectableOpenIds(visible: readonly InboxAlert[]): number[] {
  return visible.filter((a) => a.status === "open").slice(0, BULK_MAX).map((a) => a.id);
}

/** What a bulk acknowledge will touch: the selected alerts that are open (others are skipped, never errors). */
export function bulkAckTargets(selected: ReadonlySet<number>, alerts: readonly InboxAlert[]): number[] {
  return alerts.filter((a) => selected.has(a.id) && a.status === "open").map((a) => a.id).slice(0, BULK_MAX);
}

// ------------------------------------------------------------------------------------------------ new critical alerts

export interface CriticalScan {
  /** Critical, still-open alerts not seen before. Empty on the first scan (the existing backlog is not announced). */
  fresh: InboxAlert[];
  seen: Set<number>;
}
/** `seen === null` means "first load": remember everything, announce nothing. */
export function scanForNewCritical(seen: ReadonlySet<number> | null, alerts: readonly InboxAlert[]): CriticalScan {
  const next = new Set(seen ?? []);
  const fresh: InboxAlert[] = [];
  for (const a of alerts) {
    if (seen !== null && !seen.has(a.id) && a.severity === "CRITICAL" && a.status === "open") fresh.push(a);
    next.add(a.id);
  }
  return { fresh, seen: next };
}

// ------------------------------------------------------------------------------------------------ time and links

/** A UTC instant. The backend sends an explicit offset; a bare timestamp is read as UTC (the project's time contract). */
export function parseInstantMs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(iso);
  const ms = Date.parse(hasZone ? iso : `${iso}Z`);
  return Number.isFinite(ms) ? ms : null;
}

export function formatUtc(iso: string | null | undefined): string {
  const ms = parseInstantMs(iso);
  return ms === null ? "time not reported" : `${new Date(ms).toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

/** The Replay page at the moment the alert was raised, or null when it has no usable time. */
export function replayHref(createdAt: string | null | undefined): string | null {
  const ms = parseInstantMs(createdAt);
  return ms === null ? null : `/replay?t=${encodeURIComponent(formatInstantParam(ms))}`;
}

/** `?alert=<id>`: a positive integer or nothing. */
export function parseAlertParam(search: string): number | null {
  const raw = new URLSearchParams(search).get("alert");
  if (raw === null || !/^[1-9]\d{0,9}$/.test(raw)) return null;
  return Number(raw);
}

export function withAlertParam(search: string, id: number | null): string {
  const p = new URLSearchParams(search);
  if (id === null) p.delete("alert");
  else p.set("alert", String(id));
  const text = p.toString();
  return text === "" ? "" : `?${text}`;
}
