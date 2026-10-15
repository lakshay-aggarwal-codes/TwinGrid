import { fmtNumber, fmtSignedPct, fmtSpan, utcClock } from "./format";
import type { Goals } from "./goals";
import type { LiveSample } from "./liveSeries";

/**
 * Task 16: the Insights feed. Every statement is produced by a fixed rule from the numbers passed in: no model, no
 * network, no clock, no randomness. The same input always gives the same sentences. Each insight names its rule and the
 * data window it used. No per-rack attribution exists in the backend data, so none is made.
 */

export const RULE_BASED_LABEL = "Rule-based, not AI";

/** At least this much live data is needed before a trend is stated. */
export const MIN_SPAN_MS = 120_000;
export const MIN_SAMPLES = 10;
/** PUE moves smaller than this are reported as steady. */
export const PUE_TREND_PCT = 2;
/** The compared inputs are named only when one of them moved at least this much. */
export const DRIVER_MIN_PCT = 1;

export type InsightSeverity = "attention" | "info";

export interface Insight {
  /** Stable per rule, so a list keeps its keys between ticks. */
  readonly id: string;
  readonly rule: string;
  readonly severity: InsightSeverity;
  readonly text: string;
  /** The data the sentence was computed from. */
  readonly window: string;
}

export interface InsightInput {
  /** Live samples, oldest first (the window to analyse). */
  readonly samples: readonly LiveSample[];
  readonly goals: Goals;
  /** Unacknowledged alerts among the last `alertsListed` recorded, or null when alerts are unavailable. */
  readonly alerts: { readonly open: number; readonly listed: number } | null;
}

export interface Readiness {
  readonly ready: boolean;
  readonly samples: number;
  readonly spanMs: number;
}

export function readiness(samples: readonly LiveSample[]): Readiness {
  const spanMs = samples.length > 1 ? samples[samples.length - 1].t - samples[0].t : 0;
  return { ready: samples.length >= MIN_SAMPLES && spanMs >= MIN_SPAN_MS, samples: samples.length, spanMs };
}

const mean = (xs: readonly number[]): number => xs.reduce((a, b) => a + b, 0) / xs.length;

/** Mean of the first fifth against mean of the last fifth (at least one sample each): robust to a single noisy tick. */
function edgeMeans(values: readonly number[]): { head: number; tail: number } {
  const k = Math.max(1, Math.floor(values.length / 5));
  return { head: mean(values.slice(0, k)), tail: mean(values.slice(values.length - k)) };
}

/** Relative change in percent, or null when the starting value is 0 (undefined, never reported as 0). */
export function pctChange(from: number, to: number): number | null {
  return from === 0 ? null : ((to - from) / Math.abs(from)) * 100;
}

export function windowLabel(samples: readonly LiveSample[]): string {
  const first = samples[0];
  const last = samples[samples.length - 1];
  return `${utcClock(first.t)} to ${utcClock(last.t)} (${fmtSpan(last.t - first.t)}, ${samples.length} live samples received in this browser session)`;
}

function pueTrend(samples: readonly LiveSample[]): Insight | null {
  const { head, tail } = edgeMeans(samples.map((s) => s.pue));
  const change = pctChange(head, tail);
  if (change === null) return null;
  const span = fmtSpan(samples[samples.length - 1].t - samples[0].t);
  const pair = `${fmtNumber(head, 2)} ${"\u2192"} ${fmtNumber(tail, 2)}`;
  const moved = Math.abs(change) >= PUE_TREND_PCT;
  let text = moved
    ? `PUE ${change > 0 ? "rose" : "fell"} ${Math.abs(change).toFixed(1)}% over the last ${span} (${pair}).`
    : `PUE was steady (within ${PUE_TREND_PCT}%) over the last ${span} (${pair}).`;

  const it = edgeMeans(samples.map((s) => s.itKw));
  const cool = edgeMeans(samples.map((s) => s.coolingKw));
  const itPct = pctChange(it.head, it.tail);
  const coolPct = pctChange(cool.head, cool.tail);
  if (moved && itPct !== null && coolPct !== null) {
    if (Math.max(Math.abs(itPct), Math.abs(coolPct)) >= DRIVER_MIN_PCT) {
      const itLarger = Math.abs(itPct) >= Math.abs(coolPct);
      text += ` Largest move in the same window: ${itLarger ? "IT power" : "cooling power"} ${fmtSignedPct(itLarger ? itPct : coolPct)} (${itLarger ? "cooling power" : "IT power"} ${fmtSignedPct(itLarger ? coolPct : itPct)}). This is an association, not a proven cause.`;
    } else {
      text += ` IT power and cooling power each moved less than ${DRIVER_MIN_PCT}% in the same window.`;
    }
  }
  return { id: "pue-trend", rule: "pue-trend", severity: "info", text, window: windowLabel(samples) };
}

function pueGoal(samples: readonly LiveSample[], goals: Goals): Insight | null {
  const target = goals.pue;
  if (target === null) return null;
  const latest = samples[samples.length - 1].pue;
  const over = latest > target;
  const gap = pctChange(target, latest);
  const text = over
    ? `PUE ${fmtNumber(latest, 2)} is above your target of ${fmtNumber(target, 2)}${gap === null ? "" : ` (${fmtSignedPct(gap)})`}.`
    : `PUE ${fmtNumber(latest, 2)} is within your target of ${fmtNumber(target, 2)}.`;
  return { id: "pue-goal", rule: "pue-vs-target", severity: over ? "attention" : "info", text, window: `latest live sample, ${utcClock(samples[samples.length - 1].t)}` };
}

function outletGoal(samples: readonly LiveSample[], goals: Goals): Insight | null {
  const target = goals.outlet;
  if (target === null) return null;
  const peak = Math.max(...samples.map((s) => s.outletC));
  const over = peak > target;
  const span = fmtSpan(samples[samples.length - 1].t - samples[0].t);
  const text = over
    ? `Server outlet temperature peaked at ${peak.toFixed(1)} \u00b0C in the last ${span}, above your target of ${target.toFixed(1)} \u00b0C.`
    : `Server outlet temperature stayed at or below ${peak.toFixed(1)} \u00b0C in the last ${span}, within your target of ${target.toFixed(1)} \u00b0C.`;
  return { id: "outlet-goal", rule: "outlet-temperature-vs-target", severity: over ? "attention" : "info", text, window: windowLabel(samples) };
}

function carbonBasis(samples: readonly LiveSample[]): Insight | null {
  const last = samples[samples.length - 1];
  if (last.carbonGPerKwh === null || last.carbonReal !== false) return null;
  return {
    id: "carbon-basis",
    rule: "carbon-fallback-notice",
    severity: "info",
    text: `Carbon figures use a flat fallback intensity of ${last.carbonGPerKwh.toFixed(0)} gCO\u2082/kWh. It is an assumption, not grid data.`,
    window: `latest live sample, ${utcClock(last.t)}`,
  };
}

function openAlerts(alerts: InsightInput["alerts"]): Insight | null {
  if (alerts === null || alerts.open === 0) return null;
  return {
    id: "open-alerts",
    rule: "unacknowledged-alerts",
    severity: "attention",
    text: `${alerts.open} unacknowledged ${alerts.open === 1 ? "alert" : "alerts"} among the last ${alerts.listed} recorded. The backend attributes no alert to a rack.`,
    window: `last ${alerts.listed} recorded alerts`,
  };
}

/**
 * Attention items first, then information, each group in rule order. Without enough live data only the alert and
 * carbon-basis statements (which need no trend) can appear.
 */
export function computeInsights(input: InsightInput): Insight[] {
  const { samples, goals, alerts } = input;
  const all: Array<Insight | null> = [];
  if (samples.length > 0 && readiness(samples).ready) {
    all.push(pueGoal(samples, goals), outletGoal(samples, goals), pueTrend(samples));
  }
  all.push(openAlerts(alerts));
  if (samples.length > 0) all.push(carbonBasis(samples));
  const found = all.filter((i): i is Insight => i !== null);
  return [...found.filter((i) => i.severity === "attention"), ...found.filter((i) => i.severity === "info")];
}
