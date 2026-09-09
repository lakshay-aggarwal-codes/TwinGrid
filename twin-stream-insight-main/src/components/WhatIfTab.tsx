import { useState, useMemo } from 'react';
import { Slider } from '@/components/ui/slider';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { ArrowDown, Leaf } from 'lucide-react';
import type { SimConfig, CoolingMode, ScenarioResult } from '@/hooks/useSimulation';

interface Props {
  baseConfig: SimConfig;
  getResult: (cfg: SimConfig) => ScenarioResult;
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
        <div className="flex items-center justify-between">
          <Label className="text-xs text-muted-foreground">AI Optimizer</Label>
          <Switch checked={config.aiOptimizer} onCheckedChange={v => set({ aiOptimizer: v })} />
        </div>
      </div>
    </div>
  );
}

export function WhatIfTab({ baseConfig, getResult }: Props) {
  const [cfgA, setCfgA] = useState<SimConfig>({ ...baseConfig });
  const [cfgB, setCfgB] = useState<SimConfig>({ ...baseConfig, coolingMode: 'Closed-Loop', aiOptimizer: false });

  const resA = useMemo(() => getResult(cfgA), [cfgA, getResult]);
  const resB = useMemo(() => getResult(cfgB), [cfgB, getResult]);

  const better = resA.co2Kg < resB.co2Kg ? 'A' : resB.co2Kg < resA.co2Kg ? 'B' : 'equal';

  const rows = [
    { label: 'PUE', a: resA.pue.toFixed(2), b: resB.pue.toFixed(2), lower: true },
    { label: 'WUE (L/kWh)', a: resA.wue.toFixed(3), b: resB.wue.toFixed(3), lower: true },
    { label: 'Water (L/day)', a: resA.waterL.toLocaleString(), b: resB.waterL.toLocaleString(), lower: true },
    { label: 'Energy (kWh)', a: resA.energyKwh.toLocaleString(), b: resB.energyKwh.toLocaleString(), lower: true },
    { label: 'CO₂ (kg)', a: resA.co2Kg.toLocaleString(), b: resB.co2Kg.toLocaleString(), lower: true },
  ];

  return (
    <div className="space-y-4">
      <div className="flex gap-4">
        <ScenarioPanel label="Scenario A" config={cfgA} onChange={setCfgA} />
        <ScenarioPanel label="Scenario B" config={cfgB} onChange={setCfgB} />
      </div>

      {/* Comparison table */}
      <div className="card-grid-glow rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left px-4 py-3 text-xs text-muted-foreground uppercase tracking-wider">Metric</th>
              <th className="text-right px-4 py-3 text-xs text-muted-foreground uppercase tracking-wider">Scenario A</th>
              <th className="text-right px-4 py-3 text-xs text-muted-foreground uppercase tracking-wider">Scenario B</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const aVal = parseFloat(r.a.replace(/,/g, ''));
              const bVal = parseFloat(r.b.replace(/,/g, ''));
              const aBetter = r.lower ? aVal < bVal : aVal > bVal;
              const bBetter = r.lower ? bVal < aVal : bVal > aVal;
              return (
                <tr key={r.label} className="border-b border-border/50">
                  <td className="px-4 py-2.5 text-muted-foreground">{r.label}</td>
                  <td className={`px-4 py-2.5 text-right font-mono ${aBetter ? 'text-success' : ''}`}>{r.a} {aBetter && <ArrowDown className="inline h-3 w-3" />}</td>
                  <td className={`px-4 py-2.5 text-right font-mono ${bBetter ? 'text-success' : ''}`}>{r.b} {bBetter && <ArrowDown className="inline h-3 w-3" />}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Recommendation */}
      <div className={`rounded-lg p-4 flex items-center gap-3 ${better !== 'equal' ? 'bg-success/10 border border-success/30' : 'card-grid-glow'}`}>
        <Leaf className={`h-5 w-5 ${better !== 'equal' ? 'text-success' : 'text-muted-foreground'}`} />
        <div className="flex-1">
          {better !== 'equal' ? (
            <p className="text-sm text-foreground">
              <span className="font-semibold">Scenario {better}</span> is more sustainable — lower CO₂ emissions and better resource efficiency.
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">Both scenarios are equivalent in sustainability metrics.</p>
          )}
        </div>
        {better !== 'equal' && <Badge className="bg-success text-success-foreground">Recommended</Badge>}
      </div>
    </div>
  );
}
