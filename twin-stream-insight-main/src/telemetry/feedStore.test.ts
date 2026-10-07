import { describe, it, expect, vi, beforeEach, afterEach, expectTypeOf } from 'vitest';
import { createFeedStore, type FeedStore } from './feedStore';
import type { Stamped } from './stamped';
import { isLastKnown } from './stamped';
import { fakeClock, fakeTransport, liveFrame, transportState } from './testUtils';
import type { LiveStatePayload } from '@/api/apiClient';

let clock: ReturnType<typeof fakeClock>;
let t: ReturnType<typeof fakeTransport>;
let store: FeedStore;

const state = () => store.getView().freshness.state;
const open = () => t.h.onStatus!('open');
const send = (f: Partial<LiveStatePayload> = {}) => t.h.onMessage!(liveFrame(f));
const tick = (ms: number) => {
  clock.advance(ms);
  vi.advanceTimersByTime(ms);
};

beforeEach(() => {
  vi.useFakeTimers();
  clock = fakeClock();
  t = fakeTransport();
  store = createFeedStore({ connect: t.connect, clock });
  store.start();
});
afterEach(() => {
  store.stop();
  vi.useRealTimers();
});

describe('lifecycle', () => {
  it('start is idempotent (one socket) and stop disconnects', () => {
    store.start();
    expect(t.h.connects).toBe(1);
    store.stop();
    expect(t.h.disconnects).toBe(1);
    store.stop();
    expect(t.h.disconnects).toBe(1);
  });

  it('stop returns to the initial state, dropping the last frame', () => {
    open();
    send();
    store.stop();
    expect(store.getView().frame).toBeNull();
    expect(state()).toBe('connecting');
  });
});

describe('freshness transitions (fake timers)', () => {
  it('connecting -> live only on a valid frame, never on socket open', () => {
    expect(state()).toBe('connecting');
    open();
    expect(state()).toBe('connecting');
    send();
    expect(state()).toBe('live');
  });

  it('live -> stale after max(5 s, 3 x interval_s) without a frame', () => {
    open();
    send({ interval_s: 3 }); // window 9 s
    tick(9_000);
    expect(state()).toBe('live');
    tick(1_000);
    expect(state()).toBe('stale');
  });

  it('uses the default interval when the backend sends none', () => {
    open();
    send({ interval_s: undefined });
    expect(store.getView().freshness.staleAfterMs).toBe(9_000);
  });

  it('stale -> disconnected -> reconnecting -> live (only after a valid frame)', () => {
    open();
    send();
    tick(10_000);
    expect(state()).toBe('stale');

    t.h.onStatus!('closed');
    expect(state()).toBe('disconnected');

    t.h.onTransport!(transportState({ status: 'reconnecting', attempt: 1 }));
    expect(state()).toBe('reconnecting');

    t.h.onStatus!('connecting');
    open();
    // Socket reopened but no valid frame yet: must NOT be live.
    expect(state()).toBe('reconnecting');

    send();
    expect(state()).toBe('live');
  });

  it('a reconnect inside the old stale window still waits for a new valid frame', () => {
    open();
    send();
    t.h.onStatus!('closed');
    tick(1_000);
    open();
    expect(state()).not.toBe('live');
    send();
    expect(state()).toBe('live');
  });

  it('unavailable when /healthz reports the backend down; recovers on a valid frame', () => {
    open();
    send();
    t.h.onStatus!('closed');
    t.h.onTransport!(transportState({ status: 'reconnecting', attempt: 2, backend: 'unavailable' }));
    expect(state()).toBe('unavailable');
    open();
    send();
    expect(state()).toBe('live');
  });

  it('republishes the age while not live (last-known must show its age) but not while live', () => {
    open();
    send();
    const listener = vi.fn();
    store.subscribe(listener);
    tick(3_000);
    expect(listener).not.toHaveBeenCalled(); // live: ticking the clock publishes nothing
    tick(7_000); // -> stale at 10 s
    expect(listener).toHaveBeenCalledTimes(1);
    expect(store.getView().freshness.ageMs).toBe(10_000);
    tick(1_000);
    expect(store.getView().freshness.ageMs).toBe(11_000);
  });

  it('never compares ts_ingest with the client clock', () => {
    open();
    send({ ts_ingest: '2000-01-01T00:00:00+00:00', sim_time: '2000-01-01T00:00:00' });
    expect(state()).toBe('live');
  });
});

describe('seq handling', () => {
  it('ignores a duplicate seq (no new view, no listener call)', () => {
    open();
    send({ seq: 5 });
    const view = store.getView();
    const onFrame = vi.fn();
    store.onFrame(onFrame);
    send({ seq: 5, pue: 9 });
    expect(store.getView()).toBe(view);
    expect(onFrame).not.toHaveBeenCalled();
    expect(store.getView().frame!.value.pue).toBe(1.2);
  });

  it('records gap frames', () => {
    open();
    send({ seq: 1 });
    send({ seq: 2 });
    send({ seq: 6 }); // 3,4,5 missed
    expect(store.getView().seqState).toMatchObject({ last: 6, gapFrames: 3, restarted: false, unordered: false });
  });

  it('seq going backwards means the feed restarted: counters reset, flagged once', () => {
    open();
    send({ seq: 50 });
    send({ seq: 55 });
    send({ seq: 3 });
    expect(store.getView().seqState).toEqual({ last: 3, gapFrames: 0, restarted: true, restartCount: 1, unordered: false });
    send({ seq: 4 });
    expect(store.getView().seqState).toMatchObject({ last: 4, restarted: false, restartCount: 1 });
  });

  it('accepts frames without seq but flags them unordered', () => {
    open();
    send({ seq: undefined });
    expect(state()).toBe('live');
    expect(store.getView().seqState).toMatchObject({ last: null, unordered: true });
  });
});

describe('Stamped exposure', () => {
  it('the frame is only reachable stamped, with provenance and freshness', () => {
    open();
    send({ origin: 'simulated', seq: 7, ts_ingest: '2026-01-01T12:00:00+00:00', sim_time: '2026-01-01T12:35:00', sim_time_scale: 60, schema_version: 1 });
    const f = store.getView().frame!;
    expect(f.value.pue).toBe(1.2);
    expect(f.provenance).toEqual({
      origin: 'simulated',
      schemaVersion: 1,
      seq: 7,
      tsIngest: '2026-01-01T12:00:00+00:00',
      simTime: '2026-01-01T12:35:00',
      simTimeScale: 60,
      intervalS: 3,
    });
    expect(f.freshness.state).toBe('live');
    expect(isLastKnown(f)).toBe(false);
    expectTypeOf(store.getView().frame).toEqualTypeOf<Stamped<LiveStatePayload> | null>();
  });

  it('absent origin stays absent (the UI must say "Unverified source")', () => {
    open();
    send({ origin: undefined });
    expect(store.getView().frame!.provenance.origin).toBeUndefined();
  });

  it('last known is only reachable with its age and a non-live state', () => {
    open();
    send();
    tick(12_000);
    const f = store.getView().frame!;
    expect(isLastKnown(f)).toBe(true);
    expect(f.freshness.state).toBe('stale');
    expect(f.freshness.ageMs).toBe(12_000);
  });

  it('keeps only the latest frame (no history)', () => {
    open();
    send({ seq: 1, pue: 1.1 });
    send({ seq: 2, pue: 1.3 });
    expect(store.getView().frame!.value.pue).toBe(1.3);
  });
});

describe('events store', () => {
  it('uses a counter for stable unique ids, even within one millisecond, and caps the list', () => {
    for (let i = 0; i < 7; i++) store.events.push(`e${i}`, 'info');
    const ids = store.events.getSnapshot().map((e) => e.id);
    expect(ids).toEqual([7, 6, 5, 4, 3]);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
