import { useContext, useMemo, useState } from "react";
import { Download, FileDown, Printer, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { attachCapture, provenanceSection, reportToHtml, reportToMarkdown, type Report } from "@/reports/reports";
import { fetchEsgReportPdf } from "@/api/esgReport";
import { ApiError, safeMessageFor } from "@/api/apiError";
import { AuthRequiredError } from "@/authClient";
import { FeedStoreContext } from "@/telemetry/useFeed";

interface ReportDialogProps {
  report: Report | null;
  onClose: () => void;
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function downloadMarkdown(report: Report) {
  saveBlob(
    new Blob([reportToMarkdown(report)], { type: "text/markdown;charset=utf-8" }),
    `twingrid-${report.kind}-report-${report.generatedAt.replace(/[:.]/g, "-")}.md`,
  );
}

/** Client-chosen wording only; backend text never reaches the DOM. */
function esgErrorMessage(e: unknown): string {
  if (e instanceof AuthRequiredError) return safeMessageFor("unauthenticated");
  if (e instanceof ApiError) return safeMessageFor(e.kind);
  return safeMessageFor("network");
}

/**
 * Opens the report in its own window with inline CSS and prints it, so the
 * printout is just the report (not the 3D scene / app chrome behind the
 * dialog) and doesn't depend on the app's stylesheet.
 */
function printReport(report: Report) {
  const w = window.open("", "_blank");
  if (!w) {
    // Popup blocked -- tell the user rather than failing silently.
    window.alert("Your browser blocked the print window. Allow pop-ups for this site, or use Download instead.");
    return;
  }
  w.document.open();
  w.document.write(reportToHtml(report));
  w.document.close();
  w.focus();
  w.print();
}

/**
 * Renders a generated Report. Purely presentational: the report object was
 * built on demand by src/reports/reports.ts from real API data, with every
 * row already carrying its source endpoint + field.
 */
export function ReportDialog({ report: generated, onClose }: ReportDialogProps) {
  // FE-10: the feed state is captured when the report opens (the moment it was generated), from the feed store's stamped
  // data, and printed in the report's first lines. A report built without a capture is stamped here, once.
  const feed = useContext(FeedStoreContext);
  const report = useMemo(() => {
    if (!generated || generated.provenance.captured || !feed) return generated;
    const v = feed.getView();
    return attachCapture(generated, {
      frame: v.frame,
      freshness: v.freshness,
      reconnectAttempt: v.transport.detail?.attempt ?? null,
      browserTime: new Date(generated.generatedAt),
    });
  }, [generated, feed]);

  const [esg, setEsg] = useState<{ status: "idle" | "loading" | "error"; message?: string }>({ status: "idle" });
  const downloadEsg = async () => {
    setEsg({ status: "loading" });
    try {
      const file = await fetchEsgReportPdf();
      saveBlob(file.blob, file.filename);
      setEsg({ status: "idle" });
    } catch (e) {
      setEsg({ status: "error", message: esgErrorMessage(e) });
    }
  };

  return (
    <Dialog open={report !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
        {report && (
          <>
            <DialogHeader>
              <DialogTitle>{report.title}</DialogTitle>
              <DialogDescription>
                Generated {new Date(report.generatedAt).toLocaleString()} (browser time) from the data held at that moment — it
                does not update afterwards.
              </DialogDescription>
            </DialogHeader>

            {report.provenance.warnings.length > 0 && (
              <div role="note" data-testid="report-currency-warning" className="rounded-md border border-destructive/50 bg-destructive/10 p-3 space-y-1">
                {report.provenance.warnings.map((w) => (
                  <p key={w} className="text-xs font-semibold text-foreground">
                    Data currency — {w}
                  </p>
                ))}
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" onClick={() => downloadMarkdown(report)}>
                <Download className="h-3.5 w-3.5 mr-1.5" /> Download (.md)
              </Button>
              <Button size="sm" variant="outline" onClick={() => printReport(report)}>
                <Printer className="h-3.5 w-3.5 mr-1.5" /> Print / Save as PDF
              </Button>
              {report.kind === "sustainability" && (
                <Button size="sm" variant="outline" disabled={esg.status === "loading"} onClick={() => void downloadEsg()}>
                  <FileDown className="h-3.5 w-3.5 mr-1.5" />
                  {esg.status === "loading" ? "Downloading ESG report…" : "Download ESG report (PDF, from backend)"}
                </Button>
              )}
            </div>
            {esg.status === "error" && (
              <p role="alert" data-testid="esg-error" className="text-xs text-destructive">
                ESG report download failed: {esg.message}
              </p>
            )}

            {[provenanceSection(report), ...report.sections].map((s) => (
              <section key={s.title} className="space-y-1.5">
                <h3 className="text-sm font-semibold text-foreground">{s.title}</h3>
                {s.note && <p className="text-xs text-muted-foreground">{s.note}</p>}

                {s.rows && (
                  <div className="overflow-x-auto rounded-md border border-border">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-muted/50 text-muted-foreground">
                          <th className="text-left font-medium px-2.5 py-1.5">Item</th>
                          <th className="text-left font-medium px-2.5 py-1.5">Value</th>
                          <th className="text-left font-medium px-2.5 py-1.5">Source</th>
                        </tr>
                      </thead>
                      <tbody>
                        {s.rows.map((r) => (
                          <tr key={r.item} className="border-t border-border/60">
                            <td className="px-2.5 py-1.5">{r.item}</td>
                            <td className="px-2.5 py-1.5 font-mono">{r.value}</td>
                            <td className="px-2.5 py-1.5 font-mono text-[10px] text-muted-foreground">{r.source}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {s.table && (
                  <div className="overflow-x-auto rounded-md border border-border">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-muted/50 text-muted-foreground">
                          {s.table.columns.map((c) => (
                            <th key={c} className="text-left font-medium px-2.5 py-1.5">{c}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {s.table.rows.map((row, i) => (
                          <tr key={i} className="border-t border-border/60">
                            {row.map((cell, j) => (
                              <td key={j} className="px-2.5 py-1.5 align-top">{cell}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            ))}

            {report.caveats.length > 0 && (
              <div className="rounded-md border border-warning/40 bg-warning/10 p-3 space-y-1">
                <p className="flex items-center gap-1.5 text-xs font-semibold text-warning">
                  <ShieldAlert className="h-3.5 w-3.5" /> Caveats
                </p>
                <ul className="list-disc pl-4 space-y-0.5 text-xs text-foreground">
                  {report.caveats.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
