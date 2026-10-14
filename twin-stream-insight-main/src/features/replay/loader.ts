/** Task 14: load the stored history for every measurand of the replay window. One failing measurand does not blank the others. */
import { fetchTelemetryGaps, fetchTelemetrySamples } from "@/api/apiClient";
import { MEASURANDS, sensorIdFor } from "@/telemetry/history/model";
import { loadHistory, type HistoryData } from "@/telemetry/history/useTelemetryHistory";
import { buildReplaySeries, type ReplayDataset, type ReplaySeries } from "./dataset";

export interface Fetchers {
  samples: typeof fetchTelemetrySamples;
  gaps: typeof fetchTelemetryGaps;
}

export interface LoadedReplay {
  readonly dataset: ReplayDataset;
  /** Measurands whose request failed (shown by name; the others are still replayed). */
  readonly failed: readonly string[];
  readonly pagesLoaded: number;
}

/** `window.from/to` are RFC 3339 `Z`. Paging follows `next_cursor` inside `loadHistory` (page size 5000, at most 4 pages, never downsampled). */
export async function loadReplay(
  facilityId: number,
  window: { from: string; to: string },
  signal?: AbortSignal,
  fetchers: Fetchers = { samples: fetchTelemetrySamples, gaps: fetchTelemetryGaps },
): Promise<LoadedReplay> {
  const settled = await Promise.allSettled(MEASURANDS.map((m) => loadHistory(sensorIdFor(facilityId, m.id), window, signal, fetchers)));
  const series: ReplaySeries[] = [];
  const failed: string[] = [];
  let pagesLoaded = 0;
  settled.forEach((r, i) => {
    const id = MEASURANDS[i].id;
    if (r.status === "fulfilled") {
      const data: HistoryData = r.value;
      pagesLoaded += data.pagesLoaded;
      series.push(buildReplaySeries(id, facilityId, data));
    } else {
      // An aborted request is the caller's cancellation, not a failure to report.
      if (signal?.aborted) throw r.reason;
      failed.push(id);
    }
  });
  // Nothing loaded at all is an error for the caller to show (with retry), not an "empty window".
  if (failed.length === MEASURANDS.length) {
    const first = settled.find((r): r is PromiseRejectedResult => r.status === "rejected");
    throw first?.reason ?? new Error("replay load failed");
  }
  return { dataset: { series }, failed, pagesLoaded };
}
