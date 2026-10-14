/** Task 14: `?t=<RFC 3339 UTC>` (replay cursor), `?tb=` (compare time B), `?w=<hours>` (window). Pure. Anything unreadable is ignored, never trusted. */
import { DEFAULT_WINDOW_HOURS, MAX_WINDOW_HOURS } from "./model";

export const T_PARAM = "t";
export const B_PARAM = "tb";
export const W_PARAM = "w";

// An instant must say its zone: `Z` or a numeric offset. A bare local time is refused (we never guess a zone).
const INSTANT = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,3})?(Z|[+-]\d{2}:\d{2})$/;

export function parseInstantParam(raw: string | null): number | null {
  if (raw === null) return null;
  const text = raw.trim();
  const m = INSTANT.exec(text);
  if (!m) return null;
  const [y, mo, d, h, mi, s] = m.slice(1, 7).map(Number);
  // Calendar validity on the written components: 2026-02-30 and 24:00:00 are refused, not rolled over.
  const probe = new Date(Date.UTC(y, mo - 1, d, h, mi, s));
  if (probe.getUTCFullYear() !== y || probe.getUTCMonth() !== mo - 1 || probe.getUTCDate() !== d || probe.getUTCHours() !== h || probe.getUTCMinutes() !== mi || probe.getUTCSeconds() !== s) return null;
  const ms = Date.parse(text);
  return Number.isFinite(ms) ? ms : null;
}

/** RFC 3339 UTC, whole seconds, `Z`. */
export function formatInstantParam(ms: number): string {
  return new Date(Math.floor(ms / 1000) * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");
}

export interface ReplayUrl {
  tMs: number | null;
  bMs: number | null;
  hours: number;
}

export function parseReplayUrl(search: string): ReplayUrl {
  const p = new URLSearchParams(search);
  const w = Number(p.get(W_PARAM));
  const hours = Number.isInteger(w) && w >= 1 && w <= MAX_WINDOW_HOURS ? w : DEFAULT_WINDOW_HOURS;
  return { tMs: parseInstantParam(p.get(T_PARAM)), bMs: parseInstantParam(p.get(B_PARAM)), hours };
}

/** `search` with the replay parameters set (null / default removes them); every other parameter is kept. Returns "" or "?...". */
export function withReplayParams(search: string, v: { tMs: number | null; bMs: number | null; hours: number }): string {
  const p = new URLSearchParams(search);
  const put = (k: string, val: string | null) => (val === null ? p.delete(k) : p.set(k, val));
  put(T_PARAM, v.tMs === null ? null : formatInstantParam(v.tMs));
  put(B_PARAM, v.bMs === null ? null : formatInstantParam(v.bMs));
  put(W_PARAM, v.hours === DEFAULT_WINDOW_HOURS ? null : String(v.hours));
  const text = p.toString();
  return text === "" ? "" : `?${text}`;
}
