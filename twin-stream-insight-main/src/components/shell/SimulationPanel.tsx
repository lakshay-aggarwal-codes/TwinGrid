import { useState } from "react";
import { X, ArrowDown, Leaf, FileText } from "lucide-react";
import { StatusMessage } from "./StatusMessage";
import { Slider } from "@/components/ui/slider";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import type { SimConfig, CoolingMode } from "@/hooks/useSimulation";
import { useWhatIf } from "@/hooks/useWhatIf";
import type { StateResponse } from "@/api/apiClient";
import { Button } from "@/components/ui/button";
import { buildSimulationReport, type Report } from "@/reports/reports";

interface SimulationPanelProps {
  open: boolean;
  onClose: () => void;
  /** Seeds both scenarios' starting sliders -- current config, not fabricated. */
  baseConfig: SimConfig;
  /** Real live facility state, shown as an explicitly-labeled "measured now"
   * reference column alongside the two hypothetical scenarios -- this is
   * what keeps measured and projected unmistakable (Stage 9 non-negotiable). */
  liveState: StateResponse | null;
  /** Stage 13: hands a freshly built report to the page-level viewer. */
  onGenerateReport: (report: Report) => void;
}

const COOLING_MODES: CoolingMode[] = ["Auto", "Evaporative", "Closed-Loop", "Free Air", "Hybrid"];

function ScenarioSliders({ config, onChange }: { config: SimConfig; onChange: (c: SimConfig) => void }) {
  const set = (p: Partial<SimConfig>) => onChange({ ...config, ...p });
  return (
    <div className="space-y-3">
      <div>
        <Label className="text-xs text-muted-foreground">Server Util: {config.serverUtil}%</Label>
        <Slider min={10} max={100} step={1} value={[config.serverUtil]} onValueChange={([v]) => set({ serverUtil: v })} />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Outside Temp: {config.outsideTemp}°C</Label>
        <Slider min={-5} max={40} step={0.5} value={[config.outsideTemp]} onValueChange={([v]) => set({ outsideTemp: v })} />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Water Stress: {config.waterStress}</Label>
        <Slider min={0} max={1} step={0.05} value={[config.waterStress]} onValueChange={([v]) => set({ waterStress: +v.toFixed(2) })} />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Chilled Water: {config.chilledWaterSetpoint}°C</Label>
        <Slider min={5} max={15} step={0.5} value={[config.chilledWaterSetpoint]} onValueChange={([v]) => set({ chilledWaterSetpoint: v })} />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Cooling Mode</Label>
        <Select value={config.coolingMode} onValueChange={(v) => set({ coolingMode: v as CoolingMode })}>
          <SelectTrigger className="bg-muted border-border text-sm h-8"><SelectValue /></SelectTrigger>
          <SelectContent>
            {COOLING_MODES.map((m) => (
              <SelectItem key={m} value={m}>{m}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

interface MetricRow {
  label: string;
  live: number | null;
  a: number | null;
  b: number | null;
  format: (v: number) => string;
}

/**
 * Left-hand "Simulation Lab" rail. A flex sibling of the 3D viewport (like
 * SidePanel on the right) -- it narrows the viewport, never covers it, so
 * the facility stays visible per the brief's core product principle even
 * while running scenarios.
 *
 * The actual comparison logic (two constant-input 24h /api/whatif runs) is
 * the same real, already-working code the legacy dashboard's WhatIfTab
 * uses via useWhatIf.ts -- ported here into a narrower, tabbed layout
 * instead of WhatIfTab's two-side-by-side-columns, since a rail doesn't have
 * that much width. A third "Live now" column (real liveState, no extra API
 * call) makes measured-vs-projected unmistakable at a glance.
 */
export function SimulationPanel({ open, onClose, baseConfig, liveState, onGenerateReport }: SimulationPanelProps) {
  const [cfgA, setCfgA] = useState<SimConfig>({ ...baseConfig });
  const [cfgB, setCfgB] = useState<SimConfig>({ ...baseConfig, coolingMode: "Closed-Loop" });
  const [editing, setEditing] = useState<"A" | "B">("A");

  const resA = useWhatIf(cfgA);
  const resB = useWhatIf(cfgB);
  const a = resA.data;
  const b = resB.data;
  const loading = resA.loading || resB.loading;
  const error = resA.error ?? resB.error;

  if (!open) return null;

  const rows: MetricRow[] = [
    { label: "PUE", live: liveState?.pue ?? null, a: a?.mean_pue ?? null, b: b?.mean_pue ?? null, format: (v) => v.toFixed(2) },
    { label: "WUE (L/kWh)", live: liveState?.wue ?? null, a: a?.wue ?? null, b: b?.wue ?? null, format: (v) => v.toFixed(3) },
    { label: "Water (L/day)", live: null, a: a?.total_water_L ?? null, b: b?.total_water_L ?? null, format: (v) => Math.round(v).toLocaleString() },
    { label: "Energy (kWh/day)", live: null, a: a?.total_energy_kwh ?? null, b: b?.total_energy_kwh ?? null, format: (v) => Math.round(v).toLocaleString() },
    { label: "CO₂ (kg/day)", live: null, a: a?.total_co2_kg ?? null, b: b?.total_co2_kg ?? null, format: (v) => Math.round(v).toLocaleString() },
    { label: "Peak outlet (°C)", live: liveState?.server_outlet_temp_C ?? null, a: a?.max_outlet_temp_C ?? null, b: b?.max_outlet_temp_C ?? null, format: (v) => v.toFixed(1) },
  ];

  const bothLoaded = a !== null && b !== null;
  const better = !bothLoaded ? "equal" : a.total_co2_kg < b.total_co2_kg ? "A" : b.total_co2_kg < a.total_co2_kg ? "B" : "equal";
  const flatCarbon = (a !== null && !a.carbon_data_is_real) || (b !== null && !b.carbon_data_is_real);

  return (
    <aside className="w-80 border-r border-border bg-sidebar flex flex-col shrink-0">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Simulation Lab</span>
        <button onClick={onClose} className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors" aria-label="Close simulation lab">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Each scenario is an isolated 24h run on the real digital twin at constant inputs — it
          never touches or affects the live facility. "Live now" is the actual current reading,
          not part of either scenario.
        </p>

        <div className="flex items-center gap-1 rounded-md border border-border p-0.5 w-fit">
          {(["A", "B"] as const).map((k) => (
            <button
              key={k}
              onClick={() => setEditing(k)}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                editing === k ? "bg-primary/20 text-primary" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Scenario {k}
            </button>
          ))}
        </div>

        {editing === "A" ? (
          <ScenarioSliders config={cfgA} onChange={setCfgA} />
        ) : (
          <ScenarioSliders config={cfgB} onChange={setCfgB} />
        )}

        {error && (
          <StatusMessage kind="error">
            Scenario request failed: {error}
            {(a || b) && " — showing the last successful result."}
          </StatusMessage>
        )}

        <div className={`rounded-md border border-border overflow-hidden ${loading ? "opacity-60" : ""}`}>
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-border bg-card/60">
                <th className="text-left px-2.5 py-2 font-medium text-muted-foreground">Metric</th>
                <th className="text-right px-2 py-2 font-medium text-muted-foreground">Live</th>
                <th className="text-right px-2 py-2 font-medium text-muted-foreground">A</th>
                <th className="text-right px-2.5 py-2 font-medium text-muted-foreground">B</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const both = r.a !== null && r.b !== null;
                const aBetter = both && (r.a as number) < (r.b as number);
                const bBetter = both && (r.b as number) < (r.a as number);
                return (
                  <tr key={r.label} className="border-b border-border/50">
                    <td className="px-2.5 py-1.5 text-muted-foreground">{r.label}</td>
                    <td className="px-2 py-1.5 text-right font-mono text-muted-foreground">
                      {r.live === null ? "—" : r.format(r.live)}
                    </td>
                    <td className={`px-2 py-1.5 text-right font-mono ${aBetter ? "text-success" : ""}`}>
                      {r.a === null ? "—" : r.format(r.a)} {aBetter && <ArrowDown className="inline h-2.5 w-2.5" />}
                    </td>
                    <td className={`px-2.5 py-1.5 text-right font-mono ${bBetter ? "text-success" : ""}`}>
                      {r.b === null ? "—" : r.format(r.b)} {bBetter && <ArrowDown className="inline h-2.5 w-2.5" />}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {flatCarbon && (
          <p className="text-[10px] text-warning leading-snug">
            CO₂ uses the flat 475 gCO₂/kWh fallback — no real grid-intensity data loaded on the backend.
          </p>
        )}

        <div className={`rounded-md p-2.5 flex items-center gap-2 ${better !== "equal" ? "bg-success/10 border border-success/30" : "border border-border"}`}>
          <Leaf className={`h-4 w-4 shrink-0 ${better !== "equal" ? "text-success" : "text-muted-foreground"}`} />
          {!bothLoaded ? (
            error ? (
              <p className="text-xs text-muted-foreground">No result available yet.</p>
            ) : (
              <StatusMessage kind="loading">Running scenarios…</StatusMessage>
            )
          ) : better !== "equal" ? (
            <p className="text-xs text-foreground">
              <span className="font-semibold">Scenario {better}</span> emits less CO₂ over 24h.
            </p>
          ) : (
            <p className="text-xs text-muted-foreground">Both scenarios emit the same CO₂.</p>
          )}
          {better !== "equal" && <Badge className="bg-success text-success-foreground text-[10px]">Lower CO₂</Badge>}
        </div>

        {/* Only enabled once BOTH scenarios have real results and nothing is
            in flight -- a report must never cite a half-loaded comparison. */}
        <Button
          variant="outline"
          size="sm"
          className="w-full"
          disabled={!bothLoaded || loading}
          onClick={() =>
            a && b && onGenerateReport(buildSimulationReport({ cfgA, cfgB, a, b, liveState }))
          }
        >
          <FileText className="h-3.5 w-3.5 mr-1.5" />
          {bothLoaded && !loading ? "Generate simulation report" : "Report (waiting for results)"}
        </Button>
      </div>
    </aside>
  );
}
