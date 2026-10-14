/**
 * Task 14: the replay dataset and the lookups over it. PURE.
 *
 * Honesty rules (same spirit as telemetry/history/model.ts):
 *  - A value shown at time T is the stored sample at or BEFORE T ("held"), with its own timestamp and age. Nothing is
 *    interpolated, smoothed or extrapolated.
 *  - Only `quality === "ok"` samples are used. Invalid / unrecognised samples are counted, never shown as readings.
 *  - Inside a backend-reported gap, before the first sample, or long after the last one there is NO value: the lookup
 *    says why. The client never fills a gap and never infers one the backend did not report (the only client-side
 *    judgement is "this held sample is older than the sampling interval allows", and it is labelled as such).
 *  - Order: samples are used in backend order. If a page ever arrives out of order the lookup index is built from a
 *    time-sorted COPY and the violation is counted and shown.
 */
import { buildSeries, distinctOrigins, MEASURANDS, qualityClass, sensorIdFor, type MeasurandId } from "@/telemetry/history/model";
import type { HistoryData } from "@/telemetry/history/useTelemetryHistory";
import { parseInstant } from "@/contract/time";

export interface ReplaySeries {
  readonly measurand: string;
  readonly label: string;
  readonly sensorId: string;
  readonly unit: string | null;
  /** Good samples, ascending by time (parallel arrays). */
  readonly times: readonly number[];
  readonly values: readonly number[];
  readonly gaps: readonly { readonly x1: number; readonly x2: number; readonly durationS: number }[];
  /** A held sample older than this is "stale" (null = the backend gave no interval, so no judgement is made). */
  readonly staleAfterMs: number | null;
  /** Distinct `origin` strings of the stored samples, first-seen order (null = the backend reported none). */
  readonly origins: readonly (string | null)[];
  readonly excluded: number;
  readonly unreadable: number;
  readonly orderViolations: number;
  /** Stored samples exist beyond the pages loaded (the page cap was hit). */
  readonly moreAvailable: boolean;
  readonly gapsTruncated: boolean;
}

export interface ReplayDataset {
  readonly series: readonly ReplaySeries[];
}

const labelOf = (measurand: string): string => MEASURANDS.find((m) => m.id === measurand)?.label ?? measurand;

/** Two sampling intervals (or the backend's own gap threshold, if larger) before a held value is called stale. */
export function staleAfterFor(samplingIntervalS: number | null, thresholdS: number | null): number | null {
  const candidates = [samplingIntervalS === null ? null : samplingIntervalS * 2, thresholdS].filter((v): v is number => v !== null && Number.isFinite(v) && v > 0);
  return candidates.length === 0 ? null : Math.max(...candidates) * 1000;
}

export function buildReplaySeries(measurand: string, facilityId: number, data: HistoryData): ReplaySeries {
  const built = buildSeries({ sensorId: data.sensorId, unit: data.unit, items: data.items, gaps: data.gaps });
  const good = built.series.points.filter((p) => !p.gapBreak && p.v !== null && qualityClass(p.quality) === "good");
  const excluded = built.series.points.filter((p) => !p.gapBreak && qualityClass(p.quality) !== "good").length;
  const ordered = built.orderViolations === 0 ? good : [...good].sort((a, b) => a.t - b.t);
  const gaps: { x1: number; x2: number; durationS: number }[] = [];
  for (const g of data.gaps) {
    const a = parseInstant(g.start, "event");
    const b = parseInstant(g.end, "event");
    if (a.ok && b.ok && a.kind === "event" && b.kind === "event" && !a.offsetAssumed && !b.offsetAssumed) gaps.push({ x1: a.epochMs, x2: b.epochMs, durationS: g.duration_s });
  }
  return {
    measurand,
    label: labelOf(measurand),
    sensorId: data.sensorId || sensorIdFor(facilityId, measurand),
    unit: data.unit,
    times: ordered.map((p) => p.t),
    values: ordered.map((p) => p.v as number),
    gaps,
    staleAfterMs: staleAfterFor(data.samplingIntervalS, data.thresholdS),
    origins: distinctOrigins(built.series),
    excluded,
    unreadable: built.unreadable,
    orderViolations: built.orderViolations,
    moreAvailable: data.moreAvailable,
    gapsTruncated: data.gapsTruncated,
  };
}

export type ReadAt =
  | { readonly kind: "value"; readonly value: number; readonly atMs: number; /** t - atMs, >= 0. */ readonly ageMs: number; readonly stale: boolean }
  | { readonly kind: "gap"; readonly fromMs: number; readonly toMs: number; readonly durationS: number }
  | { readonly kind: "before-start"; readonly firstMs: number }
  | { readonly kind: "no-data" };

/** Index of the last element <= t in an ascending array, or -1. */
export function lastAtOrBefore(times: readonly number[], t: number): number {
  let lo = 0;
  let hi = times.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid] <= t) {
      found = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return found;
}

export function readAt(series: ReplaySeries, t: number): ReadAt {
  if (series.times.length === 0) return { kind: "no-data" };
  const i = lastAtOrBefore(series.times, t);
  if (i === -1) return { kind: "before-start", firstMs: series.times[0] };
  const gap = series.gaps.find((g) => t > g.x1 && t < g.x2);
  if (gap) return { kind: "gap", fromMs: gap.x1, toMs: gap.x2, durationS: gap.durationS };
  const ageMs = t - series.times[i];
  const stale = series.staleAfterMs !== null && ageMs > series.staleAfterMs;
  return { kind: "value", value: series.values[i], atMs: series.times[i], ageMs, stale };
}

export type Snapshot = Readonly<Record<string, ReadAt>>;

export function snapshotAt(ds: ReplayDataset, t: number): Snapshot {
  const out: Record<string, ReadAt> = {};
  for (const s of ds.series) out[s.measurand] = readAt(s, t);
  return out;
}

/** Earliest and latest good sample over all series, or null when the dataset holds none. */
export function datasetSpan(ds: ReplayDataset): { fromMs: number; toMs: number } | null {
  let from = Infinity;
  let to = -Infinity;
  for (const s of ds.series) {
    if (s.times.length === 0) continue;
    from = Math.min(from, s.times[0]);
    to = Math.max(to, s.times[s.times.length - 1]);
  }
  return from === Infinity ? null : { fromMs: from, toMs: to };
}

export const hasAnyData = (ds: ReplayDataset): boolean => datasetSpan(ds) !== null;

export type DeltaRow =
  | { readonly measurand: string; readonly label: string; readonly unit: string | null; readonly status: "ok"; readonly a: number; readonly b: number; /** b - a */ readonly delta: number; /** null when a is 0. */ readonly pct: number | null; readonly aStale: boolean; readonly bStale: boolean }
  | { readonly measurand: string; readonly label: string; readonly unit: string | null; readonly status: "unavailable"; readonly missing: "a" | "b" | "both" };

/** B minus A per measurand. A side with no value (gap, before start, none) makes the row "unavailable"; it is never filled in. */
export function compareSnapshots(ds: ReplayDataset, a: Snapshot, b: Snapshot): DeltaRow[] {
  return ds.series.map((s) => {
    const ra = a[s.measurand];
    const rb = b[s.measurand];
    const okA = ra?.kind === "value";
    const okB = rb?.kind === "value";
    const base = { measurand: s.measurand, label: s.label, unit: s.unit };
    if (!okA || !okB) return { ...base, status: "unavailable", missing: !okA && !okB ? "both" : !okA ? "a" : "b" } as DeltaRow;
    const delta = rb.value - ra.value;
    return { ...base, status: "ok", a: ra.value, b: rb.value, delta, pct: ra.value === 0 ? null : (delta / Math.abs(ra.value)) * 100, aStale: ra.stale, bStale: rb.stale };
  });
}

export const MEASURAND_IDS: readonly MeasurandId[] = MEASURANDS.map((m) => m.id);
