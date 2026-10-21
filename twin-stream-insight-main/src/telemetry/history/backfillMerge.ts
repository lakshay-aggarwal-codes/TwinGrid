/**
 * Task 23 (RT-003): honest merge of gap-backfilled samples into one sensor's stored history. PURE: no React, no
 * clock, no network, no sorting.
 *
 * Rules:
 *  - Only a `done` backfill for THIS sensor is merged. `idle`, `loading` and `unavailable` change nothing
 *    (`unavailable` is reported so the view can say the missed window was not filled).
 *  - A backfilled series whose unit differs from the history unit (or is unknown while the history unit is known)
 *    is rejected whole. No conversion.
 *  - A sample is dropped, and counted, when its event time is unreadable, before the requested window, repeats an
 *    event time already present (the history sample wins), or is earlier than the sample before it in the backfill
 *    page (the page is not re-ordered; the violation is counted).
 *  - Accepted samples are interleaved by event time with the loaded history, which stays in the order received.
 *  - Memory is bounded: at most `MAX_MERGED_BACKFILL` backfilled samples are kept (the newest ones).
 *  - No interpolation. If fewer valid samples came back than the server numbered frames in the window, the whole
 *    backfill window is added as a gap (`origin: 'backfill-shortfall'`): the seq numbers say frames are missing,
 *    not where.
 */
import type { BackfillState, BackfilledSeries, GapWindow } from '@/features/realtime-resilience/backfill';
import { eventMs } from './model';
import type { TelemetryGap, TelemetrySample } from './schema';

export const MAX_MERGED_BACKFILL = 5000;

export interface MergeInput {
  readonly sensorId: string;
  readonly unit: string | null;
  readonly items: readonly TelemetrySample[];
  readonly gaps: readonly TelemetryGap[];
}

export interface MergeRejected {
  readonly unit: number;
  readonly unreadable: number;
  readonly beforeWindow: number;
  readonly duplicate: number;
  readonly outOfOrder: number;
  readonly capped: number;
}

export interface MergeResult {
  readonly items: readonly TelemetrySample[];
  readonly gaps: readonly TelemetryGap[];
  readonly added: number;
  readonly rejected: MergeRejected;
  /** The backfill found fewer valid samples than the server numbered frames in its window. */
  readonly shortfall: { readonly missedFrames: number; readonly recovered: number; readonly from: string; readonly to: string } | null;
  /** The backfill for a missed window failed: nothing was merged and that window is not filled. */
  readonly unavailable: boolean;
  readonly unitMismatch: boolean;
}

const NONE: MergeRejected = { unit: 0, unreadable: 0, beforeWindow: 0, duplicate: 0, outOfOrder: 0, capped: 0 };

function unchanged(input: MergeInput, unavailable = false): MergeResult {
  return { items: input.items, gaps: input.gaps, added: 0, rejected: NONE, shortfall: null, unavailable, unitMismatch: false };
}

const validCount = (s: BackfilledSeries): number => {
  let n = 0;
  for (const x of s.samples) if (x.quality === 'ok' || x.quality == null) n += 1;
  return n;
};

export function mergeBackfill(input: MergeInput, backfill: BackfillState | undefined, windowFromMs: number): MergeResult {
  if (!backfill || backfill.status === 'idle' || backfill.status === 'loading') return unchanged(input);
  if (backfill.status === 'unavailable') return unchanged(input, true);
  const series = backfill.series.find((s) => s.sensorId === input.sensorId);
  if (!series) return unchanged(input);

  if ((series.unit ?? null) !== input.unit) {
    return { ...unchanged(input), rejected: { ...NONE, unit: series.samples.length }, unitMismatch: true };
  }

  const present = new Set<number>();
  for (const it of input.items) {
    const t = eventMs(it.ts_event);
    if (t !== null) present.add(t);
  }

  let unreadable = 0;
  let beforeWindow = 0;
  let duplicate = 0;
  let outOfOrder = 0;
  let prevT: number | null = null;
  const accepted: { t: number; sample: TelemetrySample }[] = [];
  for (const sample of series.samples) {
    const t = eventMs(sample.ts_event);
    if (t === null) {
      unreadable += 1;
      continue;
    }
    const wasEarlier = prevT !== null && t < prevT;
    prevT = t;
    if (wasEarlier) outOfOrder += 1;
    else if (t < windowFromMs) beforeWindow += 1;
    else if (present.has(t)) duplicate += 1;
    else {
      present.add(t); // a repeat inside the backfill page is a duplicate too
      accepted.push({ t, sample });
    }
  }
  const capped = Math.max(0, accepted.length - MAX_MERGED_BACKFILL);
  const kept = capped > 0 ? accepted.slice(capped) : accepted;

  // Interleave by event time; history keeps its received order (carry the last readable time over an unreadable one).
  const merged: TelemetrySample[] = [];
  let j = 0;
  let carry = Number.NEGATIVE_INFINITY;
  for (const it of input.items) {
    const t = eventMs(it.ts_event);
    if (t !== null) carry = t;
    while (j < kept.length && kept[j].t < carry) merged.push(kept[j++].sample);
    merged.push(it);
  }
  while (j < kept.length) merged.push(kept[j++].sample);

  const win: GapWindow = backfill.window;
  const recovered = validCount(series);
  const short = recovered < win.missedFrames;
  const gaps: TelemetryGap[] = short
    ? [...input.gaps, { start: win.from, end: win.to, duration_s: (Date.parse(win.to) - Date.parse(win.from)) / 1000, origin: 'backfill-shortfall' }]
    : input.gaps;

  return {
    items: merged,
    gaps,
    added: kept.length,
    rejected: { unit: 0, unreadable, beforeWindow, duplicate, outOfOrder, capped },
    shortfall: short ? { missedFrames: win.missedFrames, recovered, from: win.from, to: win.to } : null,
    unavailable: false,
    unitMismatch: false,
  };
}
