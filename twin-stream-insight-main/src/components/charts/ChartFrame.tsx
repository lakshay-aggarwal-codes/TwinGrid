import { useId, useState, type ReactNode } from "react";

export interface ChartColumn {
  key: string;
  header: string;
}

interface ChartFrameProps {
  /** Visible chart title (also the accessible name of the chart). */
  title: string;
  /**
   * Visible text alternative (Section 13, Charts): what is plotted, how many points, the latest value with its unit,
   * and what the data is (e.g. "simulated run result, not live"). Built only from values the backend provided.
   */
  summary: string;
  /** The same data the chart draws, as table columns/rows. Cells are already formatted strings/numbers. */
  columns: ChartColumn[];
  rows: ReadonlyArray<Readonly<Record<string, string | number>>>;
  /** Optional explanatory text shown under the title. */
  note?: ReactNode;
  /** The chart itself (hidden from the accessibility tree; the summary and the table replace it). */
  children: ReactNode;
}

/**
 * FE-19: the shared accessible shell for a chart. Visible title, a text summary linked with aria-describedby, and a
 * "View data table" toggle that shows exactly the data behind the chart. Series must additionally differ by marker/dash,
 * not colour only -- the chart's own props decide that; the table carries every value regardless.
 */
export function ChartFrame({ title, summary, columns, rows, note, children }: ChartFrameProps) {
  const id = useId();
  const [showTable, setShowTable] = useState(false);
  const titleId = `${id}-title`;
  const summaryId = `${id}-summary`;
  const tableId = `${id}-table`;

  return (
    <section aria-labelledby={titleId} className="card-grid-glow rounded-lg p-4" data-testid="chart-frame">
      <h3 id={titleId} className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">
        {title}
      </h3>
      {note}
      <p id={summaryId} data-testid="chart-summary" className="text-[11px] text-muted-foreground mb-3">
        {summary}
      </p>
      <div role="img" aria-labelledby={titleId} aria-describedby={summaryId}>
        {children}
      </div>
      <button
        type="button"
        aria-expanded={showTable}
        aria-controls={tableId}
        onClick={() => setShowTable((v) => !v)}
        className="mt-2 rounded-sm text-[11px] underline underline-offset-2 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {showTable ? "Hide data table" : "View data table"}
      </button>
      <div id={tableId} hidden={!showTable} className="mt-2 max-h-72 overflow-auto">
        {showTable && (
          <table className="w-full text-left text-xs" data-testid="chart-table">
            <caption className="sr-only">{`Data behind the chart: ${title}`}</caption>
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c.key} scope="col" className="pr-3 pb-1 font-medium text-muted-foreground">
                    {c.header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t border-border/50">
                  {columns.map((c, j) =>
                    j === 0 ? (
                      <th key={c.key} scope="row" className="pr-3 py-0.5 font-mono font-normal">
                        {r[c.key]}
                      </th>
                    ) : (
                      <td key={c.key} className="pr-3 py-0.5 font-mono">
                        {r[c.key]}
                      </td>
                    )
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
