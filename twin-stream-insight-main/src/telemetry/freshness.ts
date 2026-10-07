/**
 * FE-04: freshness state machine (roadmap §8).
 *
 *   connecting -> (valid frame) live -> (no valid frame for the stale window) stale
 *     -> (socket closed) disconnected -> (retry) reconnecting -> (valid frame) live
 *   unavailable = /healthz says the backend is down.
 *
 * Reuses `deriveLiveness` / `staleAfterMs` from `hooks/liveness.ts` (not rewritten). Age is measured on a
 * MONOTONIC clock from the moment the browser received the frame; `ts_ingest` is never compared with the client clock.
 * `live` needs an open socket AND a valid, fresh frame received on that socket: an `open` event alone never yields it.
 */
import { deriveLiveness, type SocketStatus } from '@/hooks/liveness';
import type { TransportState } from '@/api/apiClient';

export type FreshnessState = 'connecting' | 'live' | 'stale' | 'disconnected' | 'reconnecting' | 'unavailable';

export interface Freshness {
  readonly state: FreshnessState;
  /**
   * Milliseconds since the last valid frame was received (monotonic), or null if none yet. It is re-published every
   * check while the state is NOT `live` (that is when a "last known" value must show its age); while `live`
   * it is only the age at the last publish.
   */
  readonly ageMs: number | null;
  readonly staleAfterMs: number;
  /** Monotonic receipt time of the last valid frame; null if none yet. Not a data timestamp. */
  readonly lastReceivedAt: number | null;
}

export interface Clock {
  /** Monotonic milliseconds. Not related to wall-clock time and never compared with server timestamps. */
  now(): number;
}

export const monotonicClock: Clock = {
  now: () => (typeof performance !== 'undefined' && typeof performance.now === 'function' ? performance.now() : Date.now()),
};

export interface FreshnessInput {
  socket: SocketStatus;
  transport: Pick<TransportState, 'status' | 'backend'> | null;
  /** Monotonic receipt time of the last valid frame. */
  lastReceivedAt: number | null;
  /** True from any non-open socket status until a valid frame arrives on the next connection. */
  awaitingFrame: boolean;
  now: number;
  staleAfterMs: number;
}

export function deriveFreshnessState(i: FreshnessInput): FreshnessState {
  const base = deriveLiveness({ socket: i.socket, lastMessageAt: i.lastReceivedAt, now: i.now, staleAfterMs: i.staleAfterMs });

  // A frame from before a reconnect does not make a new connection live; wait for a valid frame on it.
  if ((base === 'live' || base === 'stale') && i.awaitingFrame) return 'reconnecting';
  if (base === 'live') return 'live';
  // Backend down is distinct from a socket drop, and only counts when nothing fresh is flowing.
  if (i.transport?.backend === 'unavailable') return 'unavailable';
  if ((base === 'disconnected' || base === 'connecting') && i.transport?.status === 'reconnecting') return 'reconnecting';
  return base;
}

export function buildFreshness(i: FreshnessInput): Freshness {
  return {
    state: deriveFreshnessState(i),
    ageMs: i.lastReceivedAt === null ? null : Math.max(0, i.now - i.lastReceivedAt),
    staleAfterMs: i.staleAfterMs,
    lastReceivedAt: i.lastReceivedAt,
  };
}

/** Collapse to the legacy 4-value status used by existing consumers (`hooks/liveness.ts`). */
export function toLegacyLiveness(state: FreshnessState): 'connecting' | 'live' | 'stale' | 'disconnected' {
  return state === 'reconnecting' || state === 'unavailable' ? 'disconnected' : state;
}
