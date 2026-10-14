/** Task 14: display helpers. PURE. Times are UTC event time; browser time is used for nothing. */
import { unitFor } from "@/contract/units";
import { formatUtc } from "@/telemetry/history/model";

export const fullUtc = (ms: number): string => formatUtc(ms);
/** `HH:MM:SS UTC` */
export const clockUtc = (ms: number): string => formatUtc(ms).slice(11);

export function formatSpan(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.round(s / 60);
  if (m < 120) return `${m} min`;
  return `${Math.round(m / 60)} h`;
}

/** The backend field's display precision when the unit table knows it; otherwise the number as sent (no precision claimed). */
export function formatReading(measurand: string, value: number): string {
  const info = unitFor(measurand);
  return info ? value.toFixed(info.precision) : String(value);
}

export function formatDelta(measurand: string, delta: number): string {
  const text = formatReading(measurand, Math.abs(delta));
  return delta > 0 ? `+${text}` : delta < 0 ? `−${text}` : text;
}

export type Direction = "up" | "down" | "same";
export const directionOf = (delta: number): Direction => (delta > 0 ? "up" : delta < 0 ? "down" : "same");
export const DIRECTION_TEXT: Record<Direction, { glyph: string; word: string }> = {
  up: { glyph: "▲", word: "increase" },
  down: { glyph: "▼", word: "decrease" },
  same: { glyph: "＝", word: "no change" },
};
