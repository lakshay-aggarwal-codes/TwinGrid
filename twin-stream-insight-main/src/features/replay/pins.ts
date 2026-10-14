/** Task 14: alert pins on the timeline. PURE. Alerts come from GET /api/alerts (newest first, at most 200); an alert has no rack and no state snapshot. */
import type { AlertRecord } from "@/api/models";
import { parseInstant } from "@/contract/time";
import { fractionOf } from "./model";

export const ALERT_FETCH_LIMIT = 200;

export type PinShape = "triangle" | "diamond" | "circle";
export interface AlertPin {
  readonly id: number;
  readonly ms: number;
  /** 0..1 along the window. */
  readonly fraction: number;
  readonly severity: string;
  /** Non-colour cue: CRITICAL = triangle, WARNING = diamond, anything else = circle. */
  readonly shape: PinShape;
  readonly label: string;
  readonly message: string;
  readonly acknowledged: boolean;
}

export const shapeFor = (severity: string): PinShape => (severity === "CRITICAL" ? "triangle" : severity === "WARNING" ? "diamond" : "circle");

/** Pins for the alerts inside [fromMs, toMs]. An alert with no readable event time is skipped (and counted by the caller via `skipped`). */
export function alertPins(alerts: readonly AlertRecord[], fromMs: number, toMs: number): { pins: AlertPin[]; skipped: number; /** Oldest alert returned: pins older than this may be missing. */ oldestMs: number | null } {
  const pins: AlertPin[] = [];
  let skipped = 0;
  let oldestMs: number | null = null;
  for (const a of alerts) {
    const p = parseInstant(a.created_at, "alert");
    if (!p.ok || p.kind !== "alert") {
      skipped += 1;
      continue;
    }
    oldestMs = oldestMs === null ? p.epochMs : Math.min(oldestMs, p.epochMs);
    if (p.epochMs < fromMs || p.epochMs > toMs) continue;
    pins.push({
      id: a.id,
      ms: p.epochMs,
      fraction: fractionOf(p.epochMs, fromMs, toMs),
      severity: a.severity,
      shape: shapeFor(a.severity),
      label: `${a.severity} · ${a.type}`,
      message: a.message,
      acknowledged: a.acknowledged,
    });
  }
  return { pins: pins.sort((x, y) => x.ms - y.ms || x.id - y.id), skipped, oldestMs };
}

/** True when the 200-alert fetch may not reach back to the start of the window (so an empty stretch is not proof of "no alerts"). */
export const pinsMayBeIncomplete = (returned: number, oldestMs: number | null, fromMs: number): boolean =>
  returned >= ALERT_FETCH_LIMIT && oldestMs !== null && oldestMs > fromMs;

/** Next pin strictly after / before `ms` (for the "next alert" keyboard buttons). */
export function neighbourPin(pins: readonly AlertPin[], ms: number, dir: 1 | -1): AlertPin | null {
  if (dir === 1) return pins.find((p) => p.ms > ms) ?? null;
  for (let i = pins.length - 1; i >= 0; i -= 1) if (pins[i].ms < ms) return pins[i];
  return null;
}
