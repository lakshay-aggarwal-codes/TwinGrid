import { useState } from "react";
import { X, FileText } from "lucide-react";
import { ScenarioSliders } from "@/components/scenario/ScenarioSliders";
import { PreviewResults } from "@/components/scenario/PreviewResults";
import type { SimConfig } from "@/hooks/useSimulation";
import { useWhatIf, whatIfParams } from "@/hooks/useWhatIf";
import type { StateResponse } from "@/api/apiClient";
import { Button } from "@/components/ui/button";
import { buildSimulationReport, type Report } from "@/reports/reports";

interface SimulationPanelProps {
  open: boolean;
  onClose: () => void;
  /** Seeds both scenarios' starting sliders -- current config, not fabricated. */
  baseConfig: SimConfig;
  /** Real live facility state, shown as an explicitly-labeled "Live now" reference column alongside the two
   * previews -- this is what keeps measured and projected unmistakable. */
  liveState: StateResponse | null;
  /** Hands a freshly built report to the page-level viewer. */
  onGenerateReport: (report: Report) => void;
}

/**
 * Left-hand "Simulation Lab" rail. A flex sibling of the 3D viewport: it narrows the viewport, never covers it.
 * Two constant-input 24 h /api/whatif previews, shown side by side with a separate "Live now" column. The panel
 * ranks nothing and implies no outcome; a closed panel makes no request.
 */
export function SimulationPanel({ open, onClose, baseConfig, liveState, onGenerateReport }: SimulationPanelProps) {
  const [cfgA, setCfgA] = useState<SimConfig>({ ...baseConfig });
  const [cfgB, setCfgB] = useState<SimConfig>({ ...baseConfig, coolingMode: "Closed-Loop" });
  const [editing, setEditing] = useState<"A" | "B">("A");

  const a = useWhatIf(cfgA, { enabled: open });
  const b = useWhatIf(cfgB, { enabled: open });

  if (!open) return null;

  const ra = a.result.status === "ready" ? a.result : null;
  const rb = b.result.status === "ready" ? b.result : null;
  // A report may only cite results that belong to the controls as they are now, fully settled and not stale.
  const settled =
    ra !== null &&
    rb !== null &&
    !ra.updating &&
    !rb.updating &&
    !ra.refreshFailed &&
    !rb.refreshFailed &&
    !a.isFetching &&
    !b.isFetching &&
    JSON.stringify(whatIfParams(cfgA)) === JSON.stringify(a.params) &&
    JSON.stringify(whatIfParams(cfgB)) === JSON.stringify(b.params);

  return (
    <aside aria-label="Simulation Lab" className="w-80 border-r border-border bg-sidebar flex flex-col shrink-0">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Simulation Lab</span>
        <button onClick={onClose} className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors" aria-label="Close simulation lab">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Each preview is an isolated 24h backend run at constant inputs — simulated, not measured. It never touches the live
          facility. "Live now" is the current reading, not part of either preview.
        </p>

        <div className="flex items-center gap-1 rounded-md border border-border p-0.5 w-fit" role="group" aria-label="Scenario to edit">
          {(["A", "B"] as const).map((k) => (
            <button
              key={k}
              type="button"
              aria-pressed={editing === k}
              onClick={() => setEditing(k)}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                editing === k ? "bg-primary/20 text-primary" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Scenario {k}
            </button>
          ))}
        </div>

        {editing === "A" ? (
          <ScenarioSliders idPrefix="sim-a" config={cfgA} onChange={setCfgA} />
        ) : (
          <ScenarioSliders idPrefix="sim-b" config={cfgB} onChange={setCfgB} />
        )}

        <PreviewResults a={a} b={b} liveState={liveState} compact />

        {/* Enabled only once BOTH previews are settled for the current controls: a report must never cite a
            half-loaded or stale comparison. */}
        <Button
          variant="outline"
          size="sm"
          className="w-full"
          disabled={!settled}
          onClick={() => ra && rb && onGenerateReport(buildSimulationReport({ cfgA, cfgB, a: ra.data, b: rb.data, liveState }))}
        >
          <FileText className="h-3.5 w-3.5 mr-1.5" />
          {settled ? "Generate simulation report" : "Report (waiting for results)"}
        </Button>
      </div>
    </aside>
  );
}
