/**
 * FE-18: telemetry-history view-model. PURE: no React, no clock, no network.
 *
 * Rules enforced here (and by model.test.ts / sourceGate.test.ts):
 *  - Points are kept in the order the backend returned them (server keyset order on `(ts_event, id)`, ascending).
 *    There is NO re-sorting: the backend documents the ordering, and out-of-order arrival is resolved server-side.
 *    If a page ever violates it, the violation is counted and shown, not repaired.
 *  - No downsampling, aggregation, smoothing or interpolation. Every point received is kept and listed.
 *  - `v: null` exists ONLY as a line break at a `/gaps` boundary (`gapBreak: true`). It is not a data value.
 *  - Only `quality === 'ok'` points are drawn on the line. `invalid` points (and any quality value this client does
 *    not recognise) are excluded from the line and listed; their values are never plotted (an out-of-range value
 *    would distort the axis and is not a reading).
 *  - A gap is drawn only where the backend `/gaps` endpoint reports one; the client never infers a gap or a stale flag.
 *  - Times are backend event time (UTC). Browser time is used for nothing here.
 */
import { parseInstant } from '@/contract/time';
import type { TelemetryGap, TelemetrySample } from './schema';

/** Measurand names the backend registers by default (`fac<facility id>.<measurand>`). Names only: units come from the backend response. */
export const MEASURANDS = [
  { id: 'water_flow_lpm', label: 'Water flow' },
  { id: 'water_pressure_bar', label: 'Water pressure' },
  { id: 'server_outlet_temp_C', label: 'Server outlet temperature' },
  { id: 'it_power_kw', label: 'IT power' },
  { id: 'humidity_pct', label: 'Humidity' },
] as const;
export type MeasurandId = (typeof MEASURANDS)[number]['id'];

/** The backend caps a query at 168 h (`TELEMETRY_MAX_SPAN_H`); a 422 there is shown as a request error, not worked around. */
export const WINDOWS = [
  { hours: 1, label: 'Last 1 hour' },
  { hours: 6, label: 'Last 6 hours' },
  { hours: 24, label: 'Last 24 hours' },
  { hours: 72, label: 'Last 72 hours' },
  { hours: 168, label: 'Last 168 hours (backend maximum)' },
] as const;

export const sensorIdFor = (facilityId: number, measurand: string): string => `fac${facilityId}.${measurand}`;

export interface RequestWindow {
  readonly from: string;
  readonly to: string;
  readonly fromMs: number;
  readonly toMs: number;
}

/** RFC 3339 UTC, whole seconds, `Z` suffix (the backend rejects offset-less values). `endMs` is supplied by the caller. */
export function requestWindow(endMs: number, hours: number): RequestWindow {
  const toMs = Math.floor(endMs / 1000) * 1000;
  const fromMs = toMs - hours * 3_600_000;
  const iso = (ms: number) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');
  return { from: iso(fromMs), to: iso(toMs), fromMs, toMs };
}

export type QualityClass = 'good' | 'invalid' | 'unrecognised';

export function qualityClass(raw: string | null | undefined): QualityClass {
  if (raw === 'ok') return 'good';
  if (raw === 'invalid') return 'invalid';
  return 'unrecognised';
}

export interface HistoryPoint {
  /** Event time, epoch ms (UTC). For a gap break: the midpoint of the gap. */
  readonly t: number;
  /** Event time exactly as the backend sent it (for a gap break: the gap start). */
  readonly iso: string;
  /** Backend value; `null` ONLY on a gap break. */
  readonly v: number | null;
  readonly quality: string | null;
  readonly origin: string | null;
  readonly invalidReason: string | null;
  readonly ingestIso: string | null;
  readonly gapBreak?: true;
}

/** Contract: `Series = {sensorId, unit, points[{t, v|null, quality, origin}]}`. */
export interface Series {
  readonly sensorId: string;
  readonly unit: string | null;
  readonly points: readonly HistoryPoint[];
}

export interface BuiltSeries {
  readonly series: Series;
  /** Items whose `ts_event` could not be read as an offset-qualified instant. Not drawn, not listed as points. */
  readonly unreadable: number;
  /** Points whose event time is earlier than the point before them (the backend promises ascending order). */
  readonly orderViolations: number;
}

function eventMs(text: string): number | null {
  const parsed = parseInstant(text, 'event');
  // The backend always sends `Z`. An offset-less string would mean assuming a zone: refuse it.
  return parsed.ok && parsed.kind === 'event' && !parsed.offsetAssumed ? parsed.epochMs : null;
}

export function buildSeries(input: {
  sensorId: string;
  unit: string | null | undefined;
  items: readonly TelemetrySample[];
  gaps: readonly TelemetryGap[];
}): BuiltSeries {
  const gapKeys = new Set<string>();
  for (const g of input.gaps) {
    const s = eventMs(g.start);
    const e = eventMs(g.end);
    if (s !== null && e !== null) gapKeys.add(`${s}|${e}`);
  }

  const points: HistoryPoint[] = [];
  let unreadable = 0;
  let orderViolations = 0;
  let prevMs: number | null = null;
  let lastGoodMs: number | null = null;
  let lastGoodIso: string | null = null;

  for (const item of input.items) {
    const t = eventMs(item.ts_event);
    if (t === null) {
      unreadable += 1;
      continue;
    }
    if (prevMs !== null && t < prevMs) orderViolations += 1;
    prevMs = t;

    const good = qualityClass(item.quality) === 'good';
    if (good && lastGoodMs !== null && lastGoodIso !== null && gapKeys.has(`${lastGoodMs}|${t}`)) {
      points.push({ t: (lastGoodMs + t) / 2, iso: lastGoodIso, v: null, quality: null, origin: null, invalidReason: null, ingestIso: null, gapBreak: true });
    }
    points.push({
      t,
      iso: item.ts_event,
      v: item.value,
      quality: item.quality ?? null,
      origin: item.origin ?? null,
      invalidReason: item.invalid_reason ?? null,
      ingestIso: item.ts_ingest ?? null,
    });
    if (good) {
      lastGoodMs = t;
      lastGoodIso = item.ts_event;
    }
  }
  return { series: { sensorId: input.sensorId, unit: input.unit ?? null, points }, unreadable, orderViolations };
}

export interface GapBand {
  readonly x1: number;
  readonly x2: number;
  readonly startIso: string;
  readonly endIso: string;
  readonly durationS: number;
}

export interface ChartModel {
  /** Points drawn as the line: `quality === 'ok'` plus gap breaks (`v: null`). Backend order. */
  readonly line: readonly HistoryPoint[];
  /** Points left off the line (`invalid` or an unrecognised quality). Listed, never plotted. */
  readonly excluded: readonly HistoryPoint[];
  /** Backend-reported gaps only. */
  readonly gapBands: readonly GapBand[];
  readonly goodCount: number;
}

export function buildChartModel(series: Series, gaps: readonly TelemetryGap[]): ChartModel {
  const line: HistoryPoint[] = [];
  const excluded: HistoryPoint[] = [];
  let goodCount = 0;
  for (const p of series.points) {
    if (p.gapBreak) line.push(p);
    else if (qualityClass(p.quality) === 'good') {
      line.push(p);
      goodCount += 1;
    } else excluded.push(p);
  }
  const gapBands: GapBand[] = [];
  for (const g of gaps) {
    const x1 = eventMs(g.start);
    const x2 = eventMs(g.end);
    if (x1 !== null && x2 !== null) gapBands.push({ x1, x2, startIso: g.start, endIso: g.end, durationS: g.duration_s });
  }
  return { line, excluded, gapBands, goodCount };
}

/** Distinct origin strings in first-seen order (not sorted). `null` = the backend reported none. */
export function distinctOrigins(series: Series): (string | null)[] {
  const seen: (string | null)[] = [];
  for (const p of series.points) {
    if (p.gapBreak) continue;
    if (!seen.includes(p.origin)) seen.push(p.origin);
  }
  return seen;
}

export const NOT_REPORTED = 'not reported';

export function formatUtc(ms: number): string {
  return `${new Date(ms).toISOString().replace('T', ' ').slice(0, 19)} UTC`;
}

export function formatValue(v: number, unit: string | null): string {
  return unit ? `${v} ${unit}` : `${v} (unit not reported)`;
}

export function qualityLabel(raw: string | null | undefined): string {
  switch (qualityClass(raw)) {
    case 'good':
      return 'Good (ok)';
    case 'invalid':
      return 'Invalid';
    default:
      return raw ? `Unrecognised quality: ${raw}` : `Quality ${NOT_REPORTED}`;
  }
}

/** `invalid_reason` is shown verbatim; an unknown reason is not translated or guessed. */
export function reasonLabel(raw: string | null | undefined): string {
  return raw ? raw : '—';
}
