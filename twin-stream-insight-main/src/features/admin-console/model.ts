/** Task 29: pure helpers (filters, wording, formatting). No React. The server validates everything again. */
import type { AuditItem, Delivery, User, Webhook } from "./schema";

export const ROLES = ["viewer", "operator", "admin"] as const;
export const ROLE_LABEL: Record<string, string> = { viewer: "Viewer", operator: "Operator", admin: "Admin" };
export const AUDIT_PAGE_SIZE = 50;
export const MAX_FILTER_CHARS = 64;
export const MAX_URL_CHARS = 2048;
export const EXPORT_MAX_ROWS = 10_000;

export type Parsed<T> = { ok: true; value: T } | { ok: false; error: string };

// ------------------------------------------------------------------------------------------ users
/** UX hint only (the server decides): a role can be set on someone else, to a different role. */
export function canSetRole(user: Pick<User, "is_you" | "role">, role: string): boolean {
  return !user.is_you && role !== user.role && (ROLES as readonly string[]).includes(role);
}

// ------------------------------------------------------------------------------------------ audit filters
export interface AuditForm {
  action: string;
  outcome: string;
  username: string;
  resourceType: string;
  /** `datetime-local` values: local time, no zone (converted to UTC for the request). */
  since: string;
  until: string;
}

export const EMPTY_AUDIT_FORM: AuditForm = { action: "", outcome: "", username: "", resourceType: "", since: "", until: "" };

function toIso(label: string, value: string): Parsed<string | null> {
  if (value.trim() === "") return { ok: true, value: null };
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? { ok: false, error: `${label}: enter a valid date and time.` } : { ok: true, value: d.toISOString() };
}

/**
 * The query string for the audit endpoints, or the first problem with the form. Empty fields are left out. Nothing is
 * clamped or trimmed into a different value than the person typed (beyond surrounding spaces).
 */
export function auditQuery(form: AuditForm, opts: { limit?: number; beforeId?: number | null } = {}): Parsed<string> {
  const q = new URLSearchParams();
  const text: [string, string, string][] = [
    ["action", "Action", form.action],
    ["outcome", "Outcome", form.outcome],
    ["username", "User", form.username],
    ["resource_type", "Resource type", form.resourceType],
  ];
  for (const [key, label, raw] of text) {
    const v = raw.trim();
    if (v === "") continue;
    if (v.length > MAX_FILTER_CHARS) return { ok: false, error: `${label} is longer than ${MAX_FILTER_CHARS} characters.` };
    q.set(key, v);
  }
  const since = toIso("From", form.since);
  if (!since.ok) return since;
  const until = toIso("To", form.until);
  if (!until.ok) return until;
  if (since.value && until.value && since.value > until.value) return { ok: false, error: "From is after To." };
  if (since.value) q.set("since", since.value);
  if (until.value) q.set("until", until.value);
  if (opts.limit !== undefined) q.set("limit", String(opts.limit));
  if (opts.beforeId !== undefined && opts.beforeId !== null) q.set("before_id", String(opts.beforeId));
  return { ok: true, value: q.toString() };
}

/** `2026-01-01T12:00:00+00:00` -> `2026-01-01 12:00:00 UTC` (other offsets are shown as they came). */
export function timeText(iso: string | null): string {
  if (!iso) return "unknown";
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?\+00:00$/.exec(iso);
  return m ? `${m[1]} ${m[2]} UTC` : iso;
}

/** A compact, plain-text view of an audit row's details (React escapes it; it is never rendered as HTML). */
export function describeDetails(details: AuditItem["details"], max = 120): string {
  if (!details) return "";
  const text = Object.entries(details)
    .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(", ");
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export const OUTCOME_WORD: Record<string, string> = { success: "Success", denied: "Denied", failure: "Failure" };

// ------------------------------------------------------------------------------------------ webhooks
/** How a webhook is named on screen: scheme, host and port only. The path and query are never known to the browser. */
export function webhookLabel(w: Pick<Webhook, "scheme" | "host" | "port">): string {
  return `${w.scheme}://${w.host}${w.port ? `:${w.port}` : ""}`;
}

export const ERROR_KIND_TEXT: Record<string, string> = {
  blocked_url: "URL blocked (not https or not a public address)",
  timeout: "timed out",
  connection: "could not connect",
  http_error: "the endpoint returned an error",
  redirect_refused: "redirect refused",
  request_error: "the request failed",
};

export function deliveryText(d: Pick<Delivery, "ok" | "status_code" | "error_kind" | "duration_ms">): string {
  if (d.ok) return `Delivered (HTTP ${d.status_code}) in ${d.duration_ms} ms`;
  const why = d.error_kind ? (ERROR_KIND_TEXT[d.error_kind] ?? "unknown error") : "unknown error";
  return `Failed: ${why}${d.status_code ? ` (HTTP ${d.status_code})` : ""}`;
}

export const KIND_WORD: Record<string, string> = { alert: "Alert", test: "Test" };

/** Client-side sanity only (non-empty, bounded); the server enforces https and a public address. */
export function parseWebhookUrl(text: string): Parsed<string> {
  const v = text.trim();
  if (v === "") return { ok: false, error: "Enter a webhook URL." };
  if (v.length > MAX_URL_CHARS) return { ok: false, error: `The URL is longer than ${MAX_URL_CHARS} characters.` };
  return { ok: true, value: v };
}

// ------------------------------------------------------------------------------------------ system
const CHECK_WORD: Record<string, string> = {
  ok: "OK",
  skipped: "Skipped",
  fail: "Failed",
  behind: "Behind",
  missing: "Missing",
  unknown: "Unknown",
  stale: "Stale",
  gave_up: "Gave up",
  not_running: "Not running",
};
export const checkWord = (v: string): string => CHECK_WORD[v] ?? v;
/** Only ok and skipped count as healthy; anything else (including a word this client does not know) does not. */
export const checkHealthy = (v: string): boolean => v === "ok" || v === "skipped";

const COMPONENT_WORD: Record<string, string> = {
  ok: "OK",
  loaded: "Loaded",
  degraded: "Degraded",
  not_loaded: "Not loaded",
  not_configured: "Not configured",
};
export const componentWord = (v: string): string => COMPONENT_WORD[v] ?? v;
export const componentHealthy = (v: string): boolean => v === "ok" || v === "loaded" || v === "not_configured";

export function uptimeText(seconds: number): string {
  if (seconds < 60) return `${seconds} s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} h ${m % 60} min`;
  return `${Math.floor(h / 24)} d ${h % 24} h`;
}

/** Same-origin-safe link target for the API docs: the API base plus a path the server named. */
export function docsHref(base: string, path: string): string {
  if (!base) return path;
  try {
    return new URL(path, base).toString();
  } catch {
    return path;
  }
}
