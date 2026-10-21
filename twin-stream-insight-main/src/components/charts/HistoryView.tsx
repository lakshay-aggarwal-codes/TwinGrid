import { useMemo } from 'react';
import { ProvenanceBadge, buildProvenance } from '@/provenance';
import { StateNotice } from '@/state/StateBoundary';
import type { BackfillState } from '@/features/realtime-resilience/backfill';
import { MAX_MERGED_BACKFILL, mergeBackfill } from '@/telemetry/history/backfillMerge';
import { originForProvenance } from '@/telemetry/history/origin';
import { buildChartModel, buildSeries, distinctOrigins, formatUtc, type RequestWindow } from '@/telemetry/history/model';
import { MAX_PAGES, PAGE_LIMIT, type HistoryData } from '@/telemetry/history/useTelemetryHistory';
import { HistoryChart } from './HistoryChart';
import { HistoryLegend } from './HistoryLegend';
import { HistoryTable } from './HistoryTable';

const Note = ({ id, children }: { id: string; children: React.ReactNode }) => (
  <p role="note" data-note={id} className="rounded border border-border bg-muted/40 px-3 py-2 text-xs text-foreground">
    {children}
  </p>
);

/** One sensor's stored history for one requested window. Every number on this view comes from the telemetry read API. */
export function HistoryView({ data: loaded, window, backfill }: { data: HistoryData; window: RequestWindow; backfill?: BackfillState }) {
  // Task 23: samples recovered by gap backfill are merged in (deduplicated, unit-checked, gaps kept as gaps).
  const merge = useMemo(() => mergeBackfill(loaded, backfill, window.fromMs), [loaded, backfill, window.fromMs]);
  const data = useMemo(() => ({ ...loaded, items: merge.items, gaps: merge.gaps }), [loaded, merge]);
  const built = useMemo(() => buildSeries({ sensorId: data.sensorId, unit: data.unit, items: data.items, gaps: data.gaps }), [data]);
  const model = useMemo(() => buildChartModel(built.series, data.gaps), [built, data.gaps]);
  const lastPoint = built.series.points.filter((p) => !p.gapBreak).at(-1);
  const domainEnd = lastPoint && lastPoint.t > window.toMs ? lastPoint.t : window.toMs;
  const rej = merge.rejected;
  const droppedBackfill = rej.unreadable + rej.beforeWindow + rej.duplicate + rej.outOfOrder + rej.capped;
  const origins = useMemo(() => distinctOrigins(built.series), [built]);
  const provenance = useMemo(
    () => origins.map((o) => ({ key: o ?? '(none)', view: buildProvenance({ source: { kind: null }, origin: originForProvenance(o) }) })),
    [origins],
  );

  return (
    <div className="space-y-3" data-testid="history-view" data-sensor-id={data.sensorId}>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {provenance.map((p) => (
          <ProvenanceBadge key={p.key} view={p.view} />
        ))}
        <span>
          Stored samples for <span className="font-mono text-foreground">{data.sensorId}</span>, not the live value. Event time is the backend&apos;s (UTC).
        </span>
      </div>
      <p className="text-xs text-muted-foreground" data-testid="history-facts">
        Requested window {formatUtc(window.fromMs)} to {formatUtc(window.toMs)} · unit {data.unit ?? 'not reported'} · declared interval{' '}
        {data.samplingIntervalS === null ? 'not reported' : `${data.samplingIntervalS} s`} (declared, not a guarantee of spacing) · {built.series.points.filter((p) => !p.gapBreak).length} samples loaded,{' '}
        {model.goodCount} valid, {model.excluded.length} not plotted
        {data.thresholdS !== null ? ` · gap rule: more than ${data.thresholdS} s between valid samples` : ''}
      </p>

      {origins.length > 1 && <Note id="mixed-origins">This window mixes origins. Each point&apos;s origin is in the tooltip and the table.</Note>}
      {data.moreAvailable && (
        <Note id="more-available">
          More stored samples exist in this window than are loaded ({data.pagesLoaded} pages of up to {PAGE_LIMIT}; limit {MAX_PAGES} pages). The chart shows the earliest part
          of the window. Choose a shorter window to see the rest. Nothing is downsampled.
        </Note>
      )}
      {data.thresholdS !== null && (
        <Note id="gap-granularity">
          Gaps shorter than {data.thresholdS} s ({(data.thresholdS / 60).toFixed(1)} min) are not marked: the backend reports a gap only above that spacing between valid samples.
        </Note>
      )}
      {merge.added > 0 && (
        <Note id="backfill-merged">
          {merge.added} samples recovered after a live-feed interruption (stored live telemetry for the missed window) are included
          {droppedBackfill > 0 ? `; ${droppedBackfill} recovered samples were not added (duplicate, out of order, before the window, unreadable or over the ${MAX_MERGED_BACKFILL} limit)` : ''}.
          No values were estimated for the gaps.
        </Note>
      )}
      {merge.unitMismatch && (
        <Note id="backfill-unit">Recovered samples for this sensor use a different unit than the history ({rej.unit} samples) and were not added.</Note>
      )}
      {merge.shortfall && (
        <Note id="backfill-shortfall">
          The live feed missed {merge.shortfall.missedFrames} frames between {merge.shortfall.from} and {merge.shortfall.to}; only {merge.shortfall.recovered} valid samples were recovered. That
          window is marked as a gap and is not filled in.
        </Note>
      )}
      {merge.unavailable && (
        <Note id="backfill-unavailable">Recovering the samples missed during a live-feed interruption was not possible, so that window is not filled in.</Note>
      )}
      {data.gapsTruncated && <Note id="gaps-truncated">The backend returned only the first 1000 gaps for this window; later gaps are not marked.</Note>}
      {built.unreadable > 0 && <Note id="unreadable">{built.unreadable} samples had an unreadable event time and are not shown.</Note>}
      {built.orderViolations > 0 && (
        <Note id="out-of-order">{built.orderViolations} samples arrived earlier in event time than the sample before them. They are shown in the order received.</Note>
      )}

      {model.goodCount === 0 ? (
        <StateNotice
          kind="empty"
          title="No valid samples"
          text="Samples exist in this window but none has quality ok, so there is nothing to draw. They are listed in the table."
        />
      ) : (
        <div
          role="img"
          aria-label={`Line chart of ${data.sensorId}: ${model.goodCount} valid samples, ${data.gaps.length} backend-reported gaps, ${model.excluded.length} samples not plotted. The table below lists every sample.`}
        >
          <HistoryChart model={model} unit={data.unit} domain={[window.fromMs, domainEnd]} />
        </div>
      )}
      <HistoryLegend model={model} />

      <details className="rounded border border-border p-2" data-testid="history-table-details">
        <summary className="cursor-pointer text-xs font-medium text-foreground">Data table: every sample, quality and origin</summary>
        <div className="pt-2">
          <HistoryTable series={built.series} gaps={data.gaps} />
        </div>
      </details>
    </div>
  );
}
