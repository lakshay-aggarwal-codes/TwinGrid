import { useState } from "react";
import { X, ShieldAlert, Sparkles, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusMessage } from "./StatusMessage";
import { buildOperationalReport, type Report } from "@/reports/reports";
import { fetchOptimized, type OptimizeSummary } from "@/api/apiClient";
import type { StateResponse } from "@/api/apiClient";
import type { EventItem, LatestAnomaly } from "@/hooks/useSimulation";
import { usePanelFocus } from "./usePanelFocus.ts";

interface OperationsConsoleProps {
  open: boolean;
  onClose: () => void;
  liveState: StateResponse | null;
  anomalyScore: number;
  latestAnomaly: LatestAnomaly | null;
  events: EventItem[];
  onOpenSimulationLab: () => void;
  /** Stage 13: hands a freshly built report to the page-level viewer. */
  onGenerateReport: (report: Report) => void;
}

type OptimizeState =
  | { status: "idle" }
  | { status: "confirming" }
  | { status: "running" }
  | { status: "done"; summary: OptimizeSummary }
  | { status: "error"; message: string };

// Same PUE/WUE bands as three/visualizationModes.ts, restated here as text
// labels rather than colors -- kept in sync by hand since this panel has no
// 3D dependency; if the bands there change, update these too.
function pueBand(pue: number): { label: string; ok: boolean } {
  if (pue <= 1.5) return { label: "within a good range", ok: true };
  if (pue <= 2.0) return { label: "in a fair range", ok: true };
  return { label: "in a poor range", ok: false };
}

function wueBand(wue: number): { label: string; ok: boolean } {
  if (wue <= 1.8) return { label: "within a good range", ok: true };
  if (wue <= 2.5) return { label: "in a fair range", ok: true };
  return { label: "in a poor range", ok: false };
}

/**
 * Frontend-only Operations Console (see Stage 10 prompt + user confirmation:
 * there is no LLM/agent backend in this project -- "agent" elsewhere in the
 * codebase refers to the PPO reinforcement-learning policy, a real trained
 * control model, not an autonomous reasoning system). Everything shown here
 * is either a real current value dropped into a fixed template, or a
 * confirm-gated call to a real endpoint. Nothing is generated free-text.
 */
export function OperationsConsole({
  open,
  onClose,
  liveState,
  anomalyScore,
  latestAnomaly,
  events,
  onOpenSimulationLab,
  onGenerateReport,
}: OperationsConsoleProps) {
  const [optimize, setOptimize] = useState<OptimizeState>({ status: "idle" });
  const headingRef = usePanelFocus(open);

  if (!open) return null;

  const runOptimization = () => {
    setOptimize({ status: "running" });
    fetchOptimized({})
      .then(({ summary }) => setOptimize({ status: "done", summary }))
      .catch((e: Error & { status?: number }) => {
        const message =
          e.status === 403
            ? "This account doesn't have operator permission to run cooling optimization."
            : e.status === 429
            ? "Rate limited (max 10 runs/minute) -- try again shortly."
            : e.message || "Optimization request failed.";
        setOptimize({ status: "error", message });
      });
  };

  return (
    <aside aria-label="Operations console" className="w-80 border-r border-border bg-sidebar flex flex-col shrink-0">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <h2 ref={headingRef} tabIndex={-1} className="text-xs font-semibold uppercase tracking-wider text-muted-foreground focus:outline-none">Operations Console</h2>
        <button onClick={onClose} className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label="Close operations console">
          <X aria-hidden="true" className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Real values from the live twin and its trained models, not a reasoning agent -- there's
          no LLM behind this panel. Every line below traces to a specific endpoint.
        </p>

        {/* Real current status, templated from real values -- no generated commentary. */}
        <div className="space-y-1.5">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Current status</p>
          {!liveState ? (
            <StatusMessage kind="loading">Connecting to live feed…</StatusMessage>
          ) : (
            <div className="text-xs text-foreground space-y-1">
              <p>
                PUE is <span className="font-mono">{liveState.pue.toFixed(2)}</span> — {pueBand(liveState.pue).label}.
              </p>
              <p>
                WUE is <span className="font-mono">{liveState.wue.toFixed(3)}</span> — {wueBand(liveState.wue).label}.
              </p>
              <p>
                Cooling mode: <span className="font-mono">{liveState.cooling_mode}</span>.
              </p>
            </div>
          )}
        </div>

        {/* Real anomaly detector output (autoencoder), already wired since Stage 6. */}
        <div className="space-y-1.5">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Anomaly detector</p>
          <p className="text-xs text-foreground">
            Gauge: <span className="font-mono">{Math.round(anomalyScore)}</span> / 100 (50 marks the alert threshold).
            {latestAnomaly ? ` Last alert: ${latestAnomaly.type} — ${latestAnomaly.message}` : " No active alert."}
          </p>
        </div>

        {events.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Recent events</p>
            <ul className="space-y-1">
              {events.slice(0, 5).map((e) => (
                <li key={e.id} className="text-[11px] text-muted-foreground">
                  <span className="font-mono text-foreground">{e.time}</span> — {e.message}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="h-px bg-border" />

        {/* Real, endpoint-backed actions. Read-only ones fire immediately;
            the mutating one (optimize) requires an explicit confirm step. */}
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Actions</p>

          <Button variant="outline" size="sm" className="w-full justify-start" onClick={onOpenSimulationLab}>
            Open Simulation Lab (/api/whatif)
          </Button>

          <Button
            variant="outline"
            size="sm"
            className="w-full justify-start"
            disabled={!liveState}
            onClick={() =>
              liveState &&
              onGenerateReport(
                buildOperationalReport({
                  liveState,
                  anomalyGauge: anomalyScore,
                  latestAnomaly,
                  optimizeSummary: optimize.status === "done" ? optimize.summary : null,
                }),
              )
            }
          >
            <FileText className="h-3.5 w-3.5 mr-1.5" />
            {liveState ? "Generate operational report" : "Report (waiting for live feed)"}
          </Button>

          <div className="rounded-md border border-border p-2.5 space-y-2">
            <div className="flex items-center gap-1.5 text-xs text-foreground font-medium">
              <Sparkles className="h-3.5 w-3.5 text-primary" />
              Run cooling optimization (PPO)
              <span className="ml-auto rounded border border-warning/50 px-1.5 py-px text-[9px] uppercase tracking-wider text-warning">
                Experimental — simulator-only
              </span>
            </div>
            <p className="text-[10px] text-muted-foreground leading-snug">
              Experimental: runs a trained RL policy inside the simulator via POST /api/optimize.
              Results are simulated, not measured. Requires operator permission and is
              rate-limited to 10 runs/minute. This is a backend action, logged in the audit
              trail -- confirm before running.
            </p>

            {optimize.status === "idle" && (
              <Button size="sm" variant="secondary" className="w-full" onClick={() => setOptimize({ status: "confirming" })}>
                Run optimization…
              </Button>
            )}

            {optimize.status === "confirming" && (
              <div className="space-y-1.5">
                <p className="text-[11px] text-warning flex items-center gap-1">
                  <ShieldAlert className="h-3 w-3" /> This will run an experimental 24h RL policy evaluation in the simulator.
                </p>
                <div className="flex gap-1.5">
                  <Button size="sm" className="flex-1" onClick={runOptimization}>Confirm</Button>
                  <Button size="sm" variant="ghost" className="flex-1" onClick={() => setOptimize({ status: "idle" })}>Cancel</Button>
                </div>
              </div>
            )}

            {optimize.status === "running" && (
              <StatusMessage kind="loading">Running policy evaluation…</StatusMessage>
            )}

            {optimize.status === "error" && (
              <StatusMessage kind="error" action={{ label: "Dismiss", onClick: () => setOptimize({ status: "idle" }) }}>
                {optimize.message}
              </StatusMessage>
            )}

            {optimize.status === "done" && (
              <div className="space-y-1 text-[11px] font-mono text-foreground">
                <div className="flex justify-between"><span className="text-muted-foreground">Mean PUE</span>{optimize.summary.mean_pue.toFixed(2)}</div>
                <div className="flex justify-between"><span className="text-muted-foreground">Mean WUE</span>{optimize.summary.mean_wue.toFixed(3)}</div>
                <div className="flex justify-between"><span className="text-muted-foreground">Mean Cooling Power</span>{optimize.summary.mean_cooling_power_kw.toFixed(0)} kW</div>
                <div className="flex justify-between"><span className="text-muted-foreground">Total Water</span>{Math.round(optimize.summary.total_water_consumed_L).toLocaleString()} L</div>
                <div className="flex justify-between"><span className="text-muted-foreground">Total Reward</span>{optimize.summary.total_reward.toFixed(1)}</div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Safety Violations</span>
                  <span className={optimize.summary.safety_violations > 0 ? "text-destructive" : "text-success"}>
                    {optimize.summary.safety_violations}
                  </span>
                </div>
                <Button size="sm" variant="outline" className="w-full mt-1" onClick={() => setOptimize({ status: "idle" })}>Run again</Button>
              </div>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}
