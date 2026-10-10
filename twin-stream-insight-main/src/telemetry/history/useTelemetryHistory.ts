import { fetchFacilityId, fetchTelemetryGaps, fetchTelemetrySamples } from '@/api/apiClient';
import { useApiQuery, type UseApiQueryResult } from '@/state/useApiQuery';
import type { TelemetryGap, TelemetrySample } from './schema';

/** One page is the backend maximum. Paging follows `next_cursor`; the cap below is stated on screen when it is hit. */
export const PAGE_LIMIT = 5000;
/** Most pages one view loads (4 x 5000 = 20,000 points). Beyond it the view says more data exists and asks for a narrower window. Never downsampled. */
export const MAX_PAGES = 4;
/** The backend allows 60 requests/minute: history is fetched on a window/sensor change or an explicit refresh, never on a timer. */
export const HISTORY_STALE_MS = 30_000;

export interface HistoryData {
  readonly sensorId: string;
  readonly unit: string | null;
  readonly samplingIntervalS: number | null;
  readonly thresholdS: number | null;
  readonly items: readonly TelemetrySample[];
  readonly gaps: readonly TelemetryGap[];
  readonly gapsTruncated: boolean;
  /** True when the backend still had a `next_cursor` after `MAX_PAGES` pages: stored samples exist that are NOT loaded. */
  readonly moreAvailable: boolean;
  readonly pagesLoaded: number;
}

export async function loadHistory(
  sensorId: string,
  window: { from: string; to: string },
  signal?: AbortSignal,
  fetchers = { samples: fetchTelemetrySamples, gaps: fetchTelemetryGaps },
): Promise<HistoryData> {
  const gapsPromise = fetchers.gaps(sensorId, window, signal);
  const items: TelemetrySample[] = [];
  let unit: string | null = null;
  let samplingIntervalS: number | null = null;
  let cursor: string | null = null;
  let pages = 0;
  do {
    const page = await fetchers.samples(sensorId, { ...window, limit: PAGE_LIMIT, cursor }, signal);
    pages += 1;
    if (pages === 1) {
      unit = page.unit ?? null;
      samplingIntervalS = page.sampling_interval_s ?? null;
    }
    for (const it of page.items) items.push(it);
    cursor = page.next_cursor;
  } while (cursor !== null && pages < MAX_PAGES);
  const gaps = await gapsPromise;
  return {
    sensorId,
    unit,
    samplingIntervalS,
    thresholdS: gaps.threshold_s ?? null,
    items,
    gaps: gaps.gaps,
    gapsTruncated: gaps.truncated,
    moreAvailable: cursor !== null,
    pagesLoaded: pages,
  };
}

export function useFacilityId(): UseApiQueryResult<number> {
  return useApiQuery<number>({
    queryKey: ['facility-id'],
    queryFn: ({ signal }) => fetchFacilityId(signal),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}

/** Stored history for one sensor and window as a `DataState`: no stored samples is `empty` (never a flat line or a zero). */
export function useTelemetryHistory(sensorId: string | null, window: { from: string; to: string }): UseApiQueryResult<HistoryData> {
  return useApiQuery<HistoryData>({
    queryKey: ['telemetry-history', sensorId, window.from, window.to],
    queryFn: ({ signal }) => loadHistory(sensorId as string, window, signal),
    enabled: sensorId !== null,
    staleTime: HISTORY_STALE_MS,
    refetchOnWindowFocus: false,
    refetchInterval: false,
    isEmpty: (d) => d.items.length === 0,
  });
}
