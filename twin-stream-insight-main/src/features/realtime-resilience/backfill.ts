/**
 * Task 23: gap backfill. When the live feed skips frames (a reconnect, or a client the server had to drop frames for),
 * the stored `live` telemetry for the missed window is read back through the history API so charts can be completed.
 *
 *  - The gap is detected from the server's own `seq` and bounded by the server's own `ts_ingest` of the last frame
 *    before it and the first frame after it. The browser clock is never compared with server time.
 *  - A restart (seq went backwards) or a frame without `seq`/`ts_ingest` is NOT backfilled: the window is unknown.
 *  - What comes back is stored simulated telemetry (backend `origin` is kept on every sample). The result reports how
 *    many samples were recovered next to how many frames were missed; a shortfall is shown, never filled in.
 *  - Capped: at most `MAX_BACKFILL_WINDOW_MS` of history, one page per measurand (`PAGE_LIMIT`), five requests per gap.
 */
import { fetchFacilityId, fetchTelemetrySamples } from '@/api/apiClient';
import { parseInstant } from '@/contract/time';
import { MEASURANDS, sensorIdFor } from '@/telemetry/history/model';
import type { TelemetrySample } from '@/telemetry/history/schema';
import type { FeedStore } from '@/telemetry/feedStore';
import type { Stamped } from '@/telemetry/stamped';
import type { LiveStatePayload } from '@/api/apiClient';

export const MAX_BACKFILL_WINDOW_MS = 60 * 60 * 1000;
export const BACKFILL_PAGE_LIMIT = 5000;

export interface GapWindow {
  /** RFC 3339 UTC, inclusive. */
  from: string;
  /** RFC 3339 UTC, exclusive. */
  to: string;
  /** Frames the server numbered between the two frames that this client never received. */
  missedFrames: number;
  /** True when the window was shortened to `MAX_BACKFILL_WINDOW_MS` (the oldest part is not requested). */
  truncated: boolean;
}

export interface FrameMark {
  seq: number | null;
  tsIngestMs: number | null;
}

/** The part of a frame the gap logic needs; null fields mean "not provided". */
export function markOf(frame: Stamped<LiveStatePayload>): FrameMark {
  const { seq, tsIngest } = frame.provenance;
  const parsed = typeof tsIngest === 'string' ? parseInstant(tsIngest, 'ingest') : null;
  return {
    seq: typeof seq === 'number' ? seq : null,
    // An offset-less or malformed `ts_ingest` is a contract violation: no window is derived from it.
    tsIngestMs: parsed && parsed.ok && parsed.kind === 'ingest' ? parsed.epochMs : null,
  };
}

const iso = (ms: number) => new Date(ms).toISOString();

/**
 * The window to backfill between two consecutive accepted frames, or null when there is nothing to do or the window
 * cannot be known (no previous frame, no seq/ts_ingest, restart, no missed frames, non-increasing time).
 * Pure: no clock, no network.
 */
export function gapBetween(prev: FrameMark | null, next: FrameMark, maxWindowMs = MAX_BACKFILL_WINDOW_MS): GapWindow | null {
  if (!prev || prev.seq === null || next.seq === null || prev.tsIngestMs === null || next.tsIngestMs === null) return null;
  const missed = next.seq - prev.seq - 1;
  if (missed <= 0) return null; // contiguous, a duplicate, or a restart (seq went backwards)
  // Sample `ts_event` equals the tick's `ts_ingest`: the missed ticks lie strictly between the two frames.
  const fromMs = Math.max(prev.tsIngestMs + 1, next.tsIngestMs - maxWindowMs);
  if (fromMs >= next.tsIngestMs) return null;
  return {
    from: iso(fromMs),
    to: iso(next.tsIngestMs),
    missedFrames: missed,
    truncated: fromMs > prev.tsIngestMs + 1,
  };
}

export interface BackfilledSeries {
  measurand: string;
  sensorId: string;
  /** Unit the history API reported for this sensor (Task 23: the history chart refuses a mismatch). */
  unit?: string | null;
  samples: readonly TelemetrySample[];
}

export type BackfillState =
  | { status: 'idle' }
  | { status: 'loading'; window: GapWindow }
  | { status: 'done'; window: GapWindow; series: readonly BackfilledSeries[]; recovered: number; moreAvailable: boolean }
  | { status: 'unavailable'; window: GapWindow };

export const IDLE: BackfillState = { status: 'idle' };

export interface BackfillDeps {
  facilityId: (signal?: AbortSignal) => Promise<number>;
  samples: typeof fetchTelemetrySamples;
}

const defaultDeps: BackfillDeps = { facilityId: fetchFacilityId, samples: fetchTelemetrySamples };

/** Read the five measurands for `window`. Rejects when the facility or every sensor cannot be read. */
export async function loadGap(window: GapWindow, signal: AbortSignal | undefined, deps: BackfillDeps = defaultDeps) {
  const facility = await deps.facilityId(signal);
  const settled = await Promise.allSettled(
    MEASURANDS.map(async (m) => {
      const sensorId = sensorIdFor(facility, m.id);
      const page = await deps.samples(sensorId, { from: window.from, to: window.to, limit: BACKFILL_PAGE_LIMIT }, signal);
      return { measurand: m.id, sensorId, unit: page.unit ?? null, samples: page.items, more: page.next_cursor !== null };
    })
  );
  const ok = settled.flatMap((r) => (r.status === 'fulfilled' ? [r.value] : []));
  if (ok.length === 0) throw new Error('backfill: no sensor could be read');
  return {
    series: ok.map(({ measurand, sensorId, unit, samples }): BackfilledSeries => ({ measurand, sensorId, unit, samples })),
    moreAvailable: ok.some((o) => o.more),
  };
}

/** Recovered frames = the largest per-sensor count of valid samples (one frame writes one sample per sensor). */
export function recoveredFrames(series: readonly BackfilledSeries[]): number {
  return series.reduce((max, s) => Math.max(max, s.samples.filter((x) => x.quality === 'ok' || x.quality == null).length), 0);
}

export interface Backfiller {
  start(): void;
  stop(): void;
  getState(): BackfillState;
  subscribe(listener: () => void): () => void;
}

/** Watches a feed store and, on each qualifying gap, backfills once at a time (a newer gap supersedes an older request). */
export function createBackfiller(feed: FeedStore, deps: BackfillDeps = defaultDeps): Backfiller {
  let state: BackfillState = IDLE;
  let prev: FrameMark | null = null;
  let unsubscribe: (() => void) | null = null;
  let abort: AbortController | null = null;
  const listeners = new Set<() => void>();

  const set = (next: BackfillState) => {
    state = next;
    listeners.forEach((l) => l());
  };

  async function run(window: GapWindow): Promise<void> {
    abort?.abort();
    const mine = (abort = new AbortController());
    set({ status: 'loading', window });
    try {
      const { series, moreAvailable } = await loadGap(window, mine.signal, deps);
      if (mine.signal.aborted) return;
      set({ status: 'done', window, series, recovered: recoveredFrames(series), moreAvailable });
    } catch {
      if (mine.signal.aborted) return;
      set({ status: 'unavailable', window }); // history API off, 4xx/5xx, or the facility lookup failed: say so, do not retry
    }
  }

  return {
    start() {
      if (unsubscribe) return;
      unsubscribe = feed.onFrame((frame) => {
        const mark = markOf(frame);
        const gap = gapBetween(prev, mark);
        prev = mark;
        if (gap) void run(gap);
      });
    },
    stop() {
      unsubscribe?.();
      unsubscribe = null;
      abort?.abort();
      abort = null;
      prev = null;
      if (state.status !== 'idle') set(IDLE);
    },
    getState: () => state,
    subscribe(l) {
      listeners.add(l);
      return () => void listeners.delete(l);
    },
  };
}
