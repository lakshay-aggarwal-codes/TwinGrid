import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Printer } from "lucide-react";
import { usePageTitle } from "@/hooks/usePageTitle";
import { useFeed } from "@/telemetry/useFeed";
import { ExportButtons } from "./ExportButtons";
import { ShareLinkButton } from "./ShareLinkButton";
import { buildPrintableReport, type ReportRow } from "./reportModel";
import type { ExportColumn } from "./exportTable";
import "./report-print.css";

const COLUMNS: readonly ExportColumn<ReportRow>[] = [
  { key: "section", header: "section", value: (r) => r.section },
  { key: "item", header: "item", value: (r) => r.item },
  { key: "value", header: "value", value: (r) => r.value },
  { key: "unit", header: "unit", value: (r) => r.unit },
  { key: "source_field", header: "source_field", value: (r) => r.source },
];

const BTN =
  "inline-flex items-center gap-1 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/**
 * `/report`: the executive / ESG summary as a document. Built from the latest live frame at the moment the page is
 * opened (and rebuilt only when the person presses "Refresh"), so a printed copy never changes under the reader.
 */
export default function ReportPage() {
  usePageTitle("Report");
  const frame = useFeed((v) => v.frame?.value ?? null);
  const feed = useFeed((v) => v.freshness);
  const [generatedAt, setGeneratedAt] = useState(() => new Date());
  // The report is a snapshot: it follows the feed only when refreshed.
  const [snapshot, setSnapshot] = useState(() => ({ frame, feed: { state: feed.state, ageMs: feed.ageMs } }));
  const report = useMemo(
    () => buildPrintableReport({ frame: snapshot.frame, feed: snapshot.feed, generatedAt }),
    [snapshot, generatedAt],
  );
  const refresh = () => {
    setSnapshot({ frame, feed: { state: feed.state, ageMs: feed.ageMs } });
    setGeneratedAt(new Date());
  };
  const sections = [...new Set(report.rows.map((r) => r.section))];
  const footerLine = report.provenanceFooter.map((f) => `${f.label}: ${f.value}`).join(" · ");

  return (
    <main className="report-print-root mx-auto h-full w-full max-w-4xl space-y-4 overflow-y-auto p-4">
      <header className="no-print flex flex-wrap items-center justify-between gap-3">
        <Link to="/" className="text-xs text-primary underline">Back to live twin</Link>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className={BTN} onClick={refresh}>Refresh from live data</button>
          <button type="button" className={BTN} onClick={() => window.print()}>
            <Printer className="h-3.5 w-3.5" aria-hidden="true" /> Print / Save as PDF
          </button>
          <ExportButtons label="report" columns={COLUMNS} rows={report.rows} notes={[report.carbonLabel, ...report.claimBoundary]} />
          <ShareLinkButton />
        </div>
      </header>

      <article className="report-sheet space-y-4" aria-labelledby="report-title">
        <div>
          <h1 id="report-title" className="text-xl font-semibold text-foreground">{report.title}</h1>
          <p className="text-xs text-muted-foreground">
            <strong>Simulated data.</strong> Generated {report.generatedAtUtc} (UTC, browser clock). A snapshot: it does not update after it is generated.
          </p>
        </div>

        {report.banners.map((b) => (
          <p key={b} role="note" className="report-banner rounded-md border border-destructive/60 bg-destructive/10 p-2 text-xs font-semibold text-foreground" data-testid="report-banner">{b}</p>
        ))}

        {!report.hasData && (
          <p className="rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground" data-testid="report-empty">
            Waiting for the first live frame. Open the live twin, wait for data, then press Refresh.
          </p>
        )}

        {sections.map((s) => (
          <section key={s} aria-labelledby={`rep-${s}`}>
            <h2 id={`rep-${s}`} className="mb-1 text-sm font-semibold text-foreground">{s}</h2>
            {s === "Carbon" && <p className="mb-1 text-xs text-foreground" data-testid="report-carbon-label">{report.carbonLabel}</p>}
            <div className="overflow-x-auto">
              <table className="w-full min-w-[20rem] text-left text-xs">
                <thead>
                  <tr className="border-b border-border"><th scope="col" className="py-1 pr-3 font-medium">Item</th><th scope="col" className="py-1 pr-3 font-medium">Value</th><th scope="col" className="py-1 pr-3 font-medium">Unit</th><th scope="col" className="py-1 font-medium">Source field</th></tr>
                </thead>
                <tbody>
                  {report.rows.filter((r) => r.section === s).map((r) => (
                    <tr key={`${r.section}-${r.item}`} className="border-b border-border/50">
                      <td className="py-1 pr-3">{r.item}</td><td className="py-1 pr-3 font-mono">{r.value}</td><td className="py-1 pr-3">{r.unit}</td><td className="py-1 text-muted-foreground">{r.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ))}
        {report.hasData && !sections.includes("Carbon") && <p className="text-xs text-foreground" data-testid="report-carbon-label">{report.carbonLabel}</p>}

        <section aria-labelledby="rep-boundary" className="report-boundary rounded-md border border-border p-3" data-testid="report-claim-boundary">
          <h2 id="rep-boundary" className="mb-1 text-sm font-semibold text-foreground">What this report does and does not claim</h2>
          <ul className="list-disc space-y-1 pl-5 text-xs text-foreground">
            {report.claimBoundary.map((c) => <li key={c}>{c}</li>)}
          </ul>
        </section>

        <footer className="text-xs text-muted-foreground" data-testid="report-provenance">
          <h2 className="mb-1 text-sm font-semibold text-foreground">Provenance</h2>
          <dl className="grid grid-cols-1 gap-x-4 gap-y-0.5 sm:grid-cols-[14rem_1fr]">
            {report.provenanceFooter.map((f) => (
              <div key={f.label} className="contents"><dt className="font-medium">{f.label}</dt><dd className="break-words">{f.value}</dd></div>
            ))}
          </dl>
        </footer>
      </article>

      <div className="report-print-footer" aria-hidden="true">{`Simulated data · ${footerLine}`}</div>
    </main>
  );
}
