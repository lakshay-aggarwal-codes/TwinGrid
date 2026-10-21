import { describe, expect, it } from 'vitest';
import { gapBetween, type BackfillState, type BackfilledSeries, type GapWindow } from '@/features/realtime-resilience/backfill';
import { MAX_MERGED_BACKFILL, mergeBackfill, type MergeInput } from './backfillMerge';
import type { TelemetrySample } from './schema';

const T0 = Date.UTC(2026, 2, 1, 12, 0, 0);
const iso = (offsetS: number) => new Date(T0 + offsetS * 1000).toISOString();
const sample = (offsetS: number, over: Partial<TelemetrySample> = {}): TelemetrySample => ({
  ts_event: iso(offsetS),
  ts_ingest: iso(offsetS),
  value: offsetS,
  origin: 'simulated',
  stream_id: 'live',
  quality: 'ok',
  invalid_reason: null,
  ...over,
});
const SENSOR = 'fac1.it_power_kw';
const input = (items: TelemetrySample[], over: Partial<MergeInput> = {}): MergeInput => ({ sensorId: SENSOR, unit: 'kW', items, gaps: [], ...over });
const win = (missedFrames: number, fromS = 1, toS = 30): GapWindow => ({ from: iso(fromS), to: iso(toS), missedFrames, truncated: false });
const done = (samples: TelemetrySample[], over: Partial<BackfilledSeries> = {}, missedFrames = samples.length): BackfillState => ({
  status: 'done',
  window: win(missedFrames),
  series: [{ measurand: 'it_power_kw', sensorId: SENSOR, unit: 'kW', samples, ...over }],
  recovered: samples.length,
  moreAvailable: false,
});
const times = (items: readonly TelemetrySample[]) => items.map((i) => (Date.parse(i.ts_event) - T0) / 1000);
const FROM = T0 - 3_600_000;

describe('mergeBackfill', () => {
  it('interleaves recovered samples by event time and keeps the history in the order received', () => {
    const r = mergeBackfill(input([sample(0), sample(3), sample(30)]), done([sample(6), sample(9), sample(33)]), FROM);
    expect(times(r.items)).toEqual([0, 3, 6, 9, 30, 33]);
    expect(r.added).toBe(3);
    expect(r.shortfall).toBeNull();
  });

  it('a duplicate event time is dropped and counted; the history sample wins', () => {
    const r = mergeBackfill(input([sample(3, { value: 111 })]), done([sample(3, { value: 999 }), sample(6), sample(6)]), FROM);
    expect(times(r.items)).toEqual([3, 6]);
    expect(r.items[0].value).toBe(111);
    expect(r.rejected.duplicate).toBe(2);
  });

  it('a recovered sample earlier than the one before it is not merged and is counted (no re-ordering)', () => {
    const r = mergeBackfill(input([sample(0)]), done([sample(9), sample(6), sample(12)]), FROM);
    expect(times(r.items)).toEqual([0, 9, 12]);
    expect(r.rejected.outOfOrder).toBe(1);
  });

  it('samples before the requested window, and unreadable times, are not added', () => {
    const r = mergeBackfill(input([sample(0)]), done([sample(-7200), sample(6, { ts_event: 'not a time' }), sample(9)]), FROM);
    expect(times(r.items)).toEqual([0, 9]);
    expect(r.rejected.beforeWindow).toBe(1);
    expect(r.rejected.unreadable).toBe(1);
  });

  it('a gap is a gap: fewer valid samples than missed frames marks the backfill window, with no invented points', () => {
    const r = mergeBackfill(input([sample(0)]), done([sample(3), sample(6, { quality: 'invalid' })], {}, 5), FROM);
    expect(r.items.length).toBe(3); // exactly what came back, nothing added
    expect(r.shortfall).toEqual({ missedFrames: 5, recovered: 1, from: iso(1), to: iso(30) });
    expect(r.gaps).toHaveLength(1);
    expect(r.gaps[0]).toMatchObject({ start: iso(1), end: iso(30), origin: 'backfill-shortfall' });
  });

  it('unavailable history: nothing is merged and the view is told', () => {
    const base = input([sample(0)]);
    const r = mergeBackfill(base, { status: 'unavailable', window: win(3) }, FROM);
    expect(r.unavailable).toBe(true);
    expect(r.items).toBe(base.items);
    expect(r.added).toBe(0);
  });

  it('idle, loading and undefined backfill change nothing', () => {
    const base = input([sample(0)]);
    for (const state of [undefined, { status: 'idle' } as const, { status: 'loading', window: win(2) } as const]) {
      const r = mergeBackfill(base, state, FROM);
      expect(r.items).toBe(base.items);
      expect(r.unavailable).toBe(false);
    }
  });

  it('a wrong or unknown unit rejects the whole recovered series', () => {
    for (const unit of ['W', null, undefined]) {
      const r = mergeBackfill(input([sample(0)]), done([sample(3), sample(6)], { unit }), FROM);
      expect(r.unitMismatch).toBe(true);
      expect(r.added).toBe(0);
      expect(r.rejected.unit).toBe(2);
      expect(times(r.items)).toEqual([0]);
    }
    expect(mergeBackfill(input([sample(0)], { unit: null }), done([sample(3)], { unit: null }), FROM).added).toBe(1);
  });

  it('another sensor\'s recovered series is ignored', () => {
    const r = mergeBackfill(input([sample(0)]), done([sample(3)], { sensorId: 'fac1.humidity_pct' }), FROM);
    expect(r.added).toBe(0);
    expect(r.unitMismatch).toBe(false);
  });

  it('memory is bounded: only the newest MAX_MERGED_BACKFILL recovered samples are kept', () => {
    const many = Array.from({ length: MAX_MERGED_BACKFILL + 10 }, (_, i) => sample(10 + i));
    const r = mergeBackfill(input([]), done(many), FROM);
    expect(r.added).toBe(MAX_MERGED_BACKFILL);
    expect(r.rejected.capped).toBe(10);
    expect(times(r.items)[0]).toBe(20);
  });
});

describe('restart / sequence regression guard', () => {
  it('a seq that went backwards (server restart) produces no backfill window, so nothing can be merged', () => {
    expect(gapBetween({ seq: 50, tsIngestMs: T0 }, { seq: 2, tsIngestMs: T0 + 60_000 })).toBeNull();
    expect(gapBetween({ seq: 5, tsIngestMs: T0 }, { seq: null, tsIngestMs: T0 + 3000 })).toBeNull();
  });
});
