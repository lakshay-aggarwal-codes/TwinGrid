/** Task 27: pure helpers (input checks, wording, numbers). No React. The backend validates again. */
import type { CarbonSchedule } from "./schema";

export const MAX_DURATION_H = 24;
export const MAX_LOAD_KW = 100_000;
export const DEFAULT_DURATION_H = 4;
export const DEFAULT_LOAD_KW = 100;

export const NO_VARIATION_HEADLINE = "No carbon variation in current data";
export const ESTIMATE_LABEL = "hour-of-day pattern, not a forecast";

export type Parsed<T> = { ok: true; value: T } | { ok: false; error: string };

/** A whole number of hours in [1, 24]. Nothing is clamped: an invalid entry is an error, not a different number. */
export function parseDuration(text: string): Parsed<number> {
  const t = text.trim();
  if (!/^\d+$/.test(t)) return { ok: false, error: `Enter a whole number of hours from 1 to ${MAX_DURATION_H}.` };
  const n = Number(t);
  return n >= 1 && n <= MAX_DURATION_H ? { ok: true, value: n } : { ok: false, error: `Run length must be 1 to ${MAX_DURATION_H} hours.` };
}

/** kW in (0, MAX_LOAD_KW]. */
export function parseLoadKw(text: string): Parsed<number> {
  const t = text.trim();
  const n = t === "" ? NaN : Number(t);
  if (!Number.isFinite(n) || n <= 0) return { ok: false, error: `Enter a load greater than 0 kW, up to ${MAX_LOAD_KW}.` };
  return n <= MAX_LOAD_KW ? { ok: true, value: n } : { ok: false, error: `At most ${MAX_LOAD_KW} kW.` };
}

export const hourLabel = (h: number): string => `${String(h).padStart(2, "0")}:00`;

/** "11:00 to 15:00" (the end may be on the next day; site-local time). */
export function windowLabel(start: number, end: number): string {
  return `${hourLabel(start)} to ${hourLabel(end)}`;
}

export function formatKg(kg: number): string {
  return `${kg.toFixed(1)} kg CO₂`;
}

export function formatIntensity(g: number): string {
  return `${g.toFixed(0)} gCO₂/kWh`;
}

/** The whole-hour set a window covers (wraps past midnight). */
export function windowHours(start: number, durationH: number): Set<number> {
  return new Set(Array.from({ length: durationH }, (_, i) => (start + i) % 24));
}

/** Plain wording of the saving; a saving is never worded as larger than the backend's number. */
export function savingWording(s: NonNullable<CarbonSchedule["savings"]>, baselineKind: "average_of_allowed_windows" | "reference_start"): { kind: "saves" | "same"; text: string } {
  const vs = baselineKind === "reference_start" ? "your reference start time" : "the average start time";
  if (s.emissions_kg <= 0) return { kind: "same", text: `Same emissions as ${vs}.` };
  const pct = s.pct === null ? "" : ` (${s.pct.toFixed(1)} %)`;
  return { kind: "saves", text: `Saves ${formatKg(s.emissions_kg)}${pct} vs ${vs}.` };
}

/** Text alternative for the 24-hour strip: lowest and highest hour, the best window if any. */
export function stripDescription(curve: readonly number[], best: { start_hour: number; end_hour: number } | null): string {
  let lo = 0;
  let hi = 0;
  curve.forEach((v, h) => {
    if (v < curve[lo]) lo = h;
    if (v > curve[hi]) hi = h;
  });
  const base = `Carbon intensity by site-local hour: lowest ${formatIntensity(curve[lo])} at ${hourLabel(lo)}, highest ${formatIntensity(curve[hi])} at ${hourLabel(hi)}.`;
  return best ? `${base} Best window ${windowLabel(best.start_hour, best.end_hour)}, outlined.` : base;
}

/** Only these statuses may show a window and a saving. */
export const showsWindow = (s: CarbonSchedule["status"]): boolean => s === "ok" || s === "synthetic_demo";
