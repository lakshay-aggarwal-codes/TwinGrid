/**
 * FE-04: external store that owns the live feed (replaces "latest frame in React state/context").
 *
 * - Holds ONLY the latest frame + counters (no history; history is FE-18).
 * - The bare frame never leaves this module: consumers get `Stamped<LiveStatePayload>` through `FeedView`.
 * - `seq` handling: duplicate ignored; gap counted; regression = feed restarted (state reset); missing `seq` = unordered.
 * - Freshness: see `freshness.ts`. A timer re-evaluates it between frames and publishes only when something changed.
 */
import { connectWebSocket, type LiveStatePayload, type SocketStatus, type TransportState } from '@/api/apiClient';
import { LIVENESS_CHECK_INTERVAL_MS, staleAfterMs } from '@/hooks/liveness';
import { buildFreshness, monotonicClock, type Clock, type Freshness } from './freshness';
import { createEventStore, type EventStore } from './eventStore';
import type { ProvenanceInput, Stamped } from './stamped';

export interface SeqState {
  /** Last accepted `seq`; null until a frame with `seq` has been accepted. */
  readonly last: number | null;
  /** Frames the server numbered but this client never received (since the last restart). */
  readonly gapFrames: number;
  /** True only for the frame that restarted the sequence (seq went backwards: server restarted). */
  readonly restarted: boolean;
  /** Number of restarts seen (monotonic counter so a UI can fire a one-off notice). */
  readonly restartCount: number;
  /** A frame without `seq` was accepted: ordering is not guaranteed. */
  readonly unordered: boolean;
}

export interface TransportView {
  /** Coarse socket status from the transport. */
  readonly socket: SocketStatus;
  /** Detailed transport state (attempts, next retry, /healthz probe, close reason); null until the transport reports. */
  readonly detail: TransportState | null;
}

export interface FeedView {
  readonly transport: TransportView;
  /** Latest valid frame, stamped. Null until the first valid frame. */
  readonly frame: Stamped<LiveStatePayload> | null;
  readonly receivedAtMonotonic: number | null;
  readonly seqState: SeqState;
  readonly freshness: Freshness;
}

export type FrameListener = (frame: Stamped<LiveStatePayload>) => void;

export interface FeedStore {
  /** Connect the socket and start the freshness timer. Idempotent. */
  start(): void;
  /** Disconnect, stop the timer and return to the initial state. Idempotent. */
  stop(): void;
  subscribe(listener: () => void): () => void;
  /** Referentially stable until something observable changes. */
  getView(): FeedView;
  /** Called synchronously for every ACCEPTED frame (not duplicates), e.g. for per-episode side effects. */
  onFrame(listener: FrameListener): () => void;
  readonly events: EventStore;
}

export interface FeedStoreOptions {
  connect?: typeof connectWebSocket;
  clock?: Clock;
  checkIntervalMs?: number;
}

const INITIAL_SEQ: SeqState = { last: null, gapFrames: 0, restarted: false, restartCount: 0, unordered: false };

function provenanceOf(f: LiveStatePayload): ProvenanceInput {
  return {
    origin: f.origin,
    schemaVersion: f.schema_version,
    seq: f.seq,
    tsIngest: f.ts_ingest,
    simTime: f.sim_time,
    simTimeScale: f.sim_time_scale,
    intervalS: f.interval_s,
  };
}

export function createFeedStore(options: FeedStoreOptions = {}): FeedStore {
  const connect = options.connect ?? connectWebSocket;
  const clock = options.clock ?? monotonicClock;
  const checkMs = options.checkIntervalMs ?? LIVENESS_CHECK_INTERVAL_MS;

  // ---- mutable internals (never exported) ----
  let socket: SocketStatus = 'connecting';
  let detail: TransportState | null = null;
  let bareFrame: LiveStatePayload | null = null; // the only place a bare frame exists
  let lastReceivedAt: number | null = null;
  let staleMs = staleAfterMs();
  let awaitingFrame = true;
  let seq: SeqState = INITIAL_SEQ;
  let connection: { disconnect: () => void } | null = null;
  let timer: ReturnType<typeof setInterval> | null = null;

  const listeners = new Set<() => void>();
  const frameListeners = new Set<FrameListener>();
  const events = createEventStore();

  const freshnessNow = (): Freshness =>
    buildFreshness({ socket, transport: detail, lastReceivedAt, awaitingFrame, now: clock.now(), staleAfterMs: staleMs });

  function buildView(freshness: Freshness): FeedView {
    return {
      transport: { socket, detail },
      frame:
        bareFrame && lastReceivedAt !== null
          ? { value: bareFrame, provenance: provenanceOf(bareFrame), freshness, receivedAt: lastReceivedAt }
          : null,
      receivedAtMonotonic: lastReceivedAt,
      seqState: seq,
      freshness,
    };
  }

  let view: FeedView = buildView(freshnessNow());

  function publish(): void {
    view = buildView(freshnessNow());
    listeners.forEach((l) => l());
  }

  /** Re-evaluate freshness; publish only if the state changed, or while not live (the age is what changes). */
  function recheck(): void {
    const next = freshnessNow();
    const prev = view.freshness;
    const changed = next.state !== prev.state || next.staleAfterMs !== prev.staleAfterMs;
    const ageMatters = next.state !== 'live' && next.ageMs !== null && next.ageMs !== prev.ageMs;
    if (changed || ageMatters) {
      view = buildView(next);
      listeners.forEach((l) => l());
    }
  }

  function nextSeq(frame: LiveStatePayload): SeqState | 'duplicate' {
    const s = frame.seq;
    if (typeof s !== 'number') return { ...seq, restarted: false, unordered: true };
    if (seq.last === null) return { ...seq, last: s, restarted: false };
    if (s === seq.last) return 'duplicate';
    if (s < seq.last) return { last: s, gapFrames: 0, restarted: true, restartCount: seq.restartCount + 1, unordered: false };
    return { ...seq, last: s, gapFrames: seq.gapFrames + (s - seq.last - 1), restarted: false };
  }

  function handleFrame(frame: LiveStatePayload): void {
    const result = nextSeq(frame);
    if (result === 'duplicate') return;
    seq = result;
    bareFrame = frame;
    lastReceivedAt = clock.now();
    staleMs = staleAfterMs(frame.interval_s);
    awaitingFrame = false;
    publish();
    // `publish()` has rebuilt `view`, so the listener receives the stamped frame with current freshness.
    const stamped = view.frame;
    if (stamped) frameListeners.forEach((l) => l(stamped));
  }

  function handleSocket(status: SocketStatus): void {
    socket = status;
    if (status !== 'open') awaitingFrame = true;
    publish();
  }

  function handleTransport(state: TransportState): void {
    detail = state;
    publish();
  }

  function reset(): void {
    socket = 'connecting';
    detail = null;
    bareFrame = null;
    lastReceivedAt = null;
    staleMs = staleAfterMs();
    awaitingFrame = true;
    seq = INITIAL_SEQ;
    view = buildView(freshnessNow());
  }

  return {
    start() {
      if (connection) return;
      reset();
      listeners.forEach((l) => l());
      connection = connect(handleFrame, handleSocket, handleTransport);
      timer = setInterval(recheck, checkMs);
    },
    stop() {
      if (!connection && !timer) return;
      connection?.disconnect();
      connection = null;
      if (timer) clearInterval(timer);
      timer = null;
      reset();
      events.clear();
      listeners.forEach((l) => l());
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    getView: () => view,
    onFrame(listener) {
      frameListeners.add(listener);
      return () => void frameListeners.delete(listener);
    },
    events,
  };
}
