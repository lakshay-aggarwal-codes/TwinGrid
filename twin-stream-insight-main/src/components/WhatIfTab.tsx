import { useState } from 'react';
import type { SimConfig } from '@/hooks/useSimulation';
import { useWhatIf } from '@/hooks/useWhatIf';
import { ScenarioSliders } from '@/components/scenario/ScenarioSliders';
import { PreviewResults } from '@/components/scenario/PreviewResults';

interface Props {
  baseConfig: SimConfig;
}

export function WhatIfTab({ baseConfig }: Props) {
  const [cfgA, setCfgA] = useState<SimConfig>({ ...baseConfig });
  const [cfgB, setCfgB] = useState<SimConfig>({ ...baseConfig, coolingMode: 'Closed-Loop' });

  const a = useWhatIf(cfgA, { enabled: true });
  const b = useWhatIf(cfgB, { enabled: true });

  return (
    <div className="space-y-4">
      <div className="flex gap-4">
        <section aria-label="Scenario A" className="card-grid-glow rounded-lg p-4 space-y-3 flex-1">
          <h3 className="text-sm font-semibold text-foreground">Scenario A</h3>
          <ScenarioSliders idPrefix="whatif-a" config={cfgA} onChange={setCfgA} />
        </section>
        <section aria-label="Scenario B" className="card-grid-glow rounded-lg p-4 space-y-3 flex-1">
          <h3 className="text-sm font-semibold text-foreground">Scenario B</h3>
          <ScenarioSliders idPrefix="whatif-b" config={cfgB} onChange={setCfgB} />
        </section>
      </div>

      <p className="text-xs text-muted-foreground">
        Each preview is an isolated 24 h backend run at constant inputs. It is simulated, not measured, and no policy is applied.
      </p>

      <PreviewResults a={a} b={b} />
    </div>
  );
}
