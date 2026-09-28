import {
  MODE_LABELS,
  getModeReadings,
  isCarbonDataFallback,
  type VisualizationMode,
} from "@/three/visualizationModes";
import { ThermalLegend } from "./ThermalLegend";
import { FileText } from "lucide-react";
import { StatusMessage } from "./StatusMessage";
import { buildSustainabilityReport, type Report } from "@/reports/reports";
import type { StateResponse } from "@/api/apiClient";

interface ModeLegendProps {
  mode: VisualizationMode;
  liveState: StateResponse | null;
  /** Stage 13: hands a freshly built report to the page-level viewer. */
  onGenerateReport: (report: Report) => void;
}

/**
 * Physical mode has nothing to show -- no legend renders. Thermal (Stage 7)
 * gets its own dedicated legend (two real gradient scales, inlet/outlet)
 * since a flat key-value list can't represent that well. Energy/Cooling/
 * Sustainability (Stage 8) share this generic panel. Either way, this is
 * the ONLY place the underlying real numbers are surfaced -- the 3D racks
 * themselves only carry color, so without a legend a viewer would have no
 * way to know what a color actually means.
 */
export function ModeLegend({ mode, liveState, onGenerateReport }: ModeLegendProps) {
  if (mode === "physical") return null;

  if (mode === "thermal") {
    return (
      <ThermalLegend
        reading={liveState ? { inletTempC: liveState.server_inlet_temp_C, outletTempC: liveState.server_outlet_temp_C } : null}
      />
    );
  }

  const readings = getModeReadings(mode, liveState);

  return (
    <div className="absolute bottom-4 left-4 rounded-md border border-border bg-card/85 backdrop-blur-sm px-3.5 py-2.5 max-w-[260px]">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
        {MODE_LABELS[mode]} — Facility-wide
      </p>
      {!liveState ? (
        <StatusMessage kind="loading">Connecting to live feed…</StatusMessage>
      ) : (
        <div className="space-y-0.5">
          {readings.map((r) => (
            <div key={r.label} className="flex items-baseline justify-between gap-3 font-mono text-xs">
              <span className="text-muted-foreground">{r.label}</span>
              <span className="text-foreground">{r.value}</span>
            </div>
          ))}
        </div>
      )}
      <p className="text-[10px] text-muted-foreground mt-1.5 leading-snug">
        Every rack shares this same value — no per-rack data exists yet.
      </p>
      {mode === "sustainability" && liveState && (
        <button
          onClick={() => onGenerateReport(buildSustainabilityReport(liveState))}
          className="mt-2 w-full flex items-center justify-center gap-1.5 rounded border border-border px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
        >
          <FileText className="h-3 w-3" /> Generate sustainability report
        </button>
      )}
      {isCarbonDataFallback(liveState) && (
        <p className="text-[10px] text-warning mt-1 leading-snug">
          Carbon intensity is a flat fallback figure, not live grid data.
        </p>
      )}
    </div>
  );
}
