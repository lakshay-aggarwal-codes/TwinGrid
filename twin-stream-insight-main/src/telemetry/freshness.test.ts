import { describe, it, expect } from 'vitest';
import { buildFreshness, deriveFreshnessState, toLegacyLiveness, type FreshnessInput } from './freshness';
import { staleAfterMs } from '@/hooks/liveness';

const W = staleAfterMs(3); // 9 s
const base: FreshnessInput = { socket: 'open', transport: null, lastReceivedAt: null, awaitingFrame: true, now: 100_000, staleAfterMs: W };
const st = (p: Partial<FreshnessInput>) => deriveFreshnessState({ ...base, ...p });

describe('deriveFreshnessState', () => {
  it('connecting: nothing received yet, socket connecting or merely open', () => {
    expect(st({ socket: 'connecting' })).toBe('connecting');
    expect(st({ socket: 'open' })).toBe('connecting'); // an open socket alone never yields live
  });

  it('live: open socket + a fresh valid frame', () => {
    expect(st({ lastReceivedAt: 99_000, awaitingFrame: false })).toBe('live');
  });

  it('stale: open socket but no valid frame within the window', () => {
    expect(st({ lastReceivedAt: 100_000 - W, awaitingFrame: false })).toBe('live'); // exactly at the edge
    expect(st({ lastReceivedAt: 100_000 - W - 1, awaitingFrame: false })).toBe('stale');
  });

  it('disconnected: socket closed after data', () => {
    expect(st({ socket: 'closed', lastReceivedAt: 99_000 })).toBe('disconnected');
    expect(st({ socket: 'closed' })).toBe('disconnected'); // never connected
  });

  it('reconnecting: transport is retrying', () => {
    expect(st({ socket: 'closed', lastReceivedAt: 99_000, transport: { status: 'reconnecting', backend: 'unknown' } })).toBe('reconnecting');
    expect(st({ socket: 'connecting', transport: { status: 'reconnecting', backend: 'unknown' } })).toBe('reconnecting');
  });

  it('reconnect does not yield live (or stale) before a valid frame on the new connection', () => {
    // Old frame is still inside the window and the socket just reopened: still not live.
    expect(st({ socket: 'open', lastReceivedAt: 99_000, awaitingFrame: true })).toBe('reconnecting');
    expect(st({ socket: 'open', lastReceivedAt: 50_000, awaitingFrame: true })).toBe('reconnecting');
    expect(st({ socket: 'open', lastReceivedAt: 99_500, awaitingFrame: false })).toBe('live');
  });

  it('unavailable: /healthz says the backend is down, distinct from a socket drop', () => {
    const down = { status: 'reconnecting', backend: 'unavailable' } as const;
    expect(st({ socket: 'closed', lastReceivedAt: 99_000, transport: down })).toBe('unavailable');
    expect(st({ socket: 'closed', transport: { status: 'reconnecting', backend: 'unreachable' } })).toBe('reconnecting');
  });

  it('a fresh live frame is never overridden by a stale unavailable probe flag', () => {
    expect(st({ lastReceivedAt: 99_500, awaitingFrame: false, transport: { status: 'open', backend: 'unavailable' } })).toBe('live');
  });
});

describe('buildFreshness', () => {
  it('age is measured from the monotonic receipt time and is null before any frame', () => {
    expect(buildFreshness({ ...base, lastReceivedAt: null }).ageMs).toBeNull();
    const f = buildFreshness({ ...base, lastReceivedAt: 96_000, awaitingFrame: false });
    expect(f).toEqual({ state: 'live', ageMs: 4000, staleAfterMs: W, lastReceivedAt: 96_000 });
  });
});

describe('toLegacyLiveness', () => {
  it('collapses to the four legacy values', () => {
    expect(toLegacyLiveness('reconnecting')).toBe('disconnected');
    expect(toLegacyLiveness('unavailable')).toBe('disconnected');
    expect(toLegacyLiveness('live')).toBe('live');
    expect(toLegacyLiveness('stale')).toBe('stale');
    expect(toLegacyLiveness('connecting')).toBe('connecting');
  });
});
