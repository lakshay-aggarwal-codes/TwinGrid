import { Download, Printer, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { reportToHtml, reportToMarkdown, type Report } from "@/reports/reports";

interface ReportDialogProps {
  report: Report | null;
  onClose: () => void;
}

function downloadMarkdown(report: Report) {
  const blob = new Blob([reportToMarkdown(report)], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `twingrid-${report.kind}-report-${report.generatedAt.replace(/[:.]/g, "-")}.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
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
export function ReportDialog({ report, onClose }: ReportDialogProps) {
  return (
    <Dialog open={report !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
        {report && (
          <>
            <DialogHeader>
              <DialogTitle>{report.title}</DialogTitle>
              <DialogDescription>
                Generated {new Date(report.generatedAt).toLocaleString()} from live data at that moment — it does not
                update afterwards.
              </DialogDescription>
            </DialogHeader>

            <div className="flex gap-2">
              <Button size="sm" variant="secondary" onClick={() => downloadMarkdown(report)}>
                <Download className="h-3.5 w-3.5 mr-1.5" /> Download (.md)
              </Button>
              <Button size="sm" variant="outline" onClick={() => printReport(report)}>
                <Printer className="h-3.5 w-3.5 mr-1.5" /> Print / Save as PDF
              </Button>
            </div>

            {report.sections.map((s) => (
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
