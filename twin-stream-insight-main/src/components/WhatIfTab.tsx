import { useState } from 'react';
import { Slider } from '@/components/ui/slider';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { ArrowDown, Leaf } from 'lucide-react';
import type { SimConfig, CoolingMode } from '@/hooks/useSimulation';
import { useWhatIf } from '@/hooks/useWhatIf';

interface Props {
  baseConfig: SimConfig;
}

function ScenarioPanel({ label, config, onChange }: {
  label: string; config: SimConfig; onChange: (c: SimConfig) => void;
}) {
  const set = (p: Partial<SimConfig>) => onChange({ ...config, ...p });
  return (
    <div className="card-grid-glow rounded-lg p-4 space-y-3 flex-1">
      <h3 className="text-sm font-semibold text-foreground">{label}</h3>
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
          <Select value={config.coolingMode} onValueChange={v => set({ coolingMode: v as CoolingMode })}>
            <SelectTrigger className="bg-muted border-border text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              {['Auto', 'Evaporative', 'Closed-Loop', 'Free Air', 'Hybrid'].map(m => (
                <SelectItem key={m} value={m}>{m}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </div>
  );
}

interface MetricRow {
  label: string;
  a: number | null;
  b: number | null;
  format: (v: number) => string;
}

export function WhatIfTab({ baseConfig }: Props) {
  const [cfgA, setCfgA] = useState<SimConfig>({ ...baseConfig });
  const [cfgB, setCfgB] = useState<SimConfig>({ ...baseConfig, coolingMode: 'Closed-Loop' });

  const resA = useWhatIf(cfgA);
  const resB = useWhatIf(cfgB);
  const a = resA.data;
  const b = resB.data;
  const loading = resA.loading || resB.loading;
  const error = resA.error ?? resB.error;

  const rows: MetricRow[] = [
    { label: 'PUE', a: a?.mean_pue ?? null, b: b?.mean_pue ?? null, format: (v) => v.toFixed(2) },
    { label: 'WUE (L/kWh)', a: a?.wue ?? null, b: b?.wue ?? null, format: (v) => v.toFixed(3) },
    { label: 'Water (L/day)', a: a?.total_water_L ?? null, b: b?.total_water_L ?? null, format: (v) => Math.round(v).toLocaleString() },
    { label: 'Energy (kWh/day)', a: a?.total_energy_kwh ?? null, b: b?.total_energy_kwh ?? null, format: (v) => Math.round(v).toLocaleString() },
    { label: 'CO₂ (kg/day)', a: a?.total_co2_kg ?? null, b: b?.total_co2_kg ?? null, format: (v) => Math.round(v).toLocaleString() },
    { label: 'Peak outlet temp (°C)', a: a?.max_outlet_temp_C ?? null, b: b?.max_outlet_temp_C ?? null, format: (v) => v.toFixed(1) },
  ];

  const bothLoaded = a !== null && b !== null;
  const better = !bothLoaded ? 'equal' : a.total_co2_kg < b.total_co2_kg ? 'A' : b.total_co2_kg < a.total_co2_kg ? 'B' : 'equal';
  const flatCarbon = (a !== null && !a.carbon_data_is_real) || (b !== null && !b.carbon_data_is_real);

  return (
    <div className="space-y-4">
      <div className="flex gap-4">
        <ScenarioPanel label="Scenario A" config={cfgA} onChange={setCfgA} />
        <ScenarioPanel label="Scenario B" config={cfgB} onChange={setCfgB} />
      </div>

      <p className="text-xs text-muted-foreground">
        Results come from the backend digital twin: an isolated 24 h run at constant inputs
        {a ? ` (${a.basis})` : ''}. The AI optimizer policy is not applied here.
        {loading && ' Updating…'}
      </p>
      {error && (
        <div role="alert" className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          What-if request failed: {error}
          {(a || b) && ' — showing the last successful result.'}
        </div>
      )}

      {/* Comparison table */}
      <div className={`card-grid-glow rounded-lg overflow-hidden ${loading ? 'opacity-70' : ''}`}>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left px-4 py-3 text-xs text-muted-foreground uppercase tracking-wider">Metric</th>
              <th className="text-right px-4 py-3 text-xs text-muted-foreground uppercase tracking-wider">Scenario A</th>
              <th className="text-right px-4 py-3 text-xs text-muted-foreground uppercase tracking-wider">Scenario B</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const both = r.a !== null && r.b !== null;
              const aBetter = both && (r.a as number) < (r.b as number);
              const bBetter = both && (r.b as number) < (r.a as number);
              return (
                <tr key={r.label} className="border-b border-border/50">
                  <td className="px-4 py-2.5 text-muted-foreground">{r.label}</td>
                  <td className={`px-4 py-2.5 text-right font-mono ${aBetter ? 'text-success' : ''}`}>
                    {r.a === null ? '—' : r.format(r.a)} {aBetter && <ArrowDown className="inline h-3 w-3" />}
                  </td>
                  <td className={`px-4 py-2.5 text-right font-mono ${bBetter ? 'text-success' : ''}`}>
                    {r.b === null ? '—' : r.format(r.b)} {bBetter && <ArrowDown className="inline h-3 w-3" />}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {flatCarbon && (
        <p className="text-xs text-muted-foreground">
          CO₂ uses the flat fallback of 475 gCO₂/kWh (no real grid-intensity data loaded on the backend).
        </p>
      )}

      {/* Recommendation */}
      <div className={`rounded-lg p-4 flex items-center gap-3 ${better !== 'equal' ? 'bg-success/10 border border-success/30' : 'card-grid-glow'}`}>
        <Leaf className={`h-5 w-5 ${better !== 'equal' ? 'text-success' : 'text-muted-foreground'}`} />
        <div className="flex-1">
          {!bothLoaded ? (
            <p className="text-sm text-muted-foreground">{error ? 'No result available yet.' : 'Running scenarios…'}</p>
          ) : better !== 'equal' ? (
            <p className="text-sm text-foreground">
              <span className="font-semibold">Scenario {better}</span> emits less CO₂ over the simulated 24 h.
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">Both scenarios emit the same CO₂.</p>
          )}
        </div>
        {better !== 'equal' && <Badge className="bg-success text-success-foreground">Lower CO₂</Badge>}
      </div>
    </div>
  );
}
