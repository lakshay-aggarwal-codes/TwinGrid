import { useState } from 'react';
import { classifyOrigin } from '@/provenance';
import { originForProvenance } from '@/telemetry/history/origin';
import { NOT_REPORTED, formatValue, qualityLabel, reasonLabel, type Series } from '@/telemetry/history/model';
import type { TelemetryGap } from '@/telemetry/history/schema';

export const TABLE_PAGE_SIZE = 200;

/**
 * Accessible alternative to the chart: every point received, in the backend's order, with its quality, origin and
 * (for invalid samples) the backend's reason. Paged so a large window does not become one enormous table; nothing is dropped.
 */
export function HistoryTable({ series, gaps }: { series: Series; gaps: readonly TelemetryGap[] }) {
  const rows = series.points.filter((p) => !p.gapBreak);
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(rows.length / TABLE_PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const slice = rows.slice(current * TABLE_PAGE_SIZE, (current + 1) * TABLE_PAGE_SIZE);

  return (
    <div className="space-y-3" data-testid="history-table">
      <table className="w-full text-left text-xs">
        <caption className="pb-1 text-left text-muted-foreground">
          Stored samples, backend order (event time ascending). Times are UTC event time from the backend.
        </caption>
        <thead>
          <tr className="border-b border-border">
            <th scope="col" className="py-1 pr-3 font-medium">Event time (UTC)</th>
            <th scope="col" className="py-1 pr-3 font-medium">Value</th>
            <th scope="col" className="py-1 pr-3 font-medium">Quality</th>
            <th scope="col" className="py-1 pr-3 font-medium">Origin</th>
            <th scope="col" className="py-1 pr-3 font-medium">Invalid reason</th>
            <th scope="col" className="py-1 font-medium">Ingested (server, UTC)</th>
          </tr>
        </thead>
        <tbody>
          {slice.map((p, i) => (
            <tr key={`${p.iso}-${current * TABLE_PAGE_SIZE + i}`} className="border-b border-border/50" data-quality={p.quality ?? 'none'}>
              <td className="py-1 pr-3">{p.iso}</td>
              <td className="py-1 pr-3">{p.v === null ? NOT_REPORTED : formatValue(p.v, series.unit)}</td>
              <td className="py-1 pr-3">{qualityLabel(p.quality)}</td>
              <td className="py-1 pr-3">{classifyOrigin(originForProvenance(p.origin)).text}</td>
              <td className="py-1 pr-3">{reasonLabel(p.invalidReason)}</td>
              <td className="py-1">{p.ingestIso ?? NOT_REPORTED}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {pages > 1 && (
        <nav aria-label="Table pages" className="flex items-center gap-3 text-xs">
          <button type="button" className="rounded border border-border px-2 py-1 disabled:opacity-50" disabled={current === 0} onClick={() => setPage(current - 1)}>
            Previous
          </button>
          <span role="status" aria-live="polite">
            Page {current + 1} of {pages} ({rows.length} samples)
          </span>
          <button type="button" className="rounded border border-border px-2 py-1 disabled:opacity-50" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>
            Next
          </button>
        </nav>
      )}
      {gaps.length > 0 && (
        <table className="w-full text-left text-xs" data-testid="history-gaps-table">
          <caption className="pb-1 text-left text-muted-foreground">Gaps reported by the backend (between consecutive valid samples).</caption>
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className="py-1 pr-3 font-medium">Last valid sample before (UTC)</th>
              <th scope="col" className="py-1 pr-3 font-medium">First valid sample after (UTC)</th>
              <th scope="col" className="py-1 font-medium">Duration (s)</th>
            </tr>
          </thead>
          <tbody>
            {gaps.map((g) => (
              <tr key={`${g.start}-${g.end}`} className="border-b border-border/50">
                <td className="py-1 pr-3">{g.start}</td>
                <td className="py-1 pr-3">{g.end}</td>
                <td className="py-1">{g.duration_s}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
