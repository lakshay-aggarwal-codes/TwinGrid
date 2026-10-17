import { ProvenanceStrip, buildProvenance } from '@/provenance';
import { WHATIF_METRICS } from '@/hooks/useWhatIf';
import type { WhatIfResponse } from '@/api/apiClient';
import { controlText, weatherPlantText } from '@/scenarios/model';
import { runProvenance } from '@/runs/model';
import type { RunResult } from '@/runs/schema';

const NA = (
  <span title="Not available">
    <span aria-hidden="true">—</span>
    <span className="sr-only">not available</span>
  </span>
);

/**
 * A completed, verified run result. The caller renders this only after `status === 'completed'`, a successful result
 * fetch and `verifyResult`. Numbers are the backend's own; nothing is recomputed here, and a missing value is "not
 * available", never 0.
 */
export function RunResultPanel({ result }: { result: RunResult }) {
  const view = buildProvenance(runProvenance(result));
  const outputs = (result.outputs ?? {}) as unknown as WhatIfResponse;
  const p = result.provenance ?? null;
  const params = Object.entries(result.parameters ?? {});
  return (
    <section aria-label="Run result" className="space-y-2 rounded-md border border-border p-3" data-testid="run-result">
      <h3 className="text-sm font-semibold text-foreground">Result (simulated)</h3>
      <ProvenanceStrip view={view} />
      <p className="text-[11px] text-muted-foreground" data-testid="run-result-weather-plant">
        {weatherPlantText({ weather_source: p?.weather_source, plant: p?.plant })}
      </p>
      <p className="text-[11px] text-muted-foreground">{controlText({ control: p?.control })}</p>
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full text-sm">
          <caption className="sr-only">Outputs of this simulated run</caption>
          <tbody>
            {WHATIF_METRICS.map((m) => {
              const v = m.pick(outputs);
              return (
                <tr key={m.key} className="border-b border-border/50">
                  <th scope="row" className="px-3 py-2 text-left font-normal text-muted-foreground">
                    {m.label}
                  </th>
                  <td className="px-3 py-2 text-right font-mono">{typeof v === 'number' && Number.isFinite(v) ? m.format(v) : NA}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {view.flags.some((f) => f.id === 'fallback') && (
        <p className="text-[11px] text-muted-foreground" data-testid="run-fallback-carbon">
          CO₂ uses a fallback carbon intensity (a flat constant); the backend reports it is not real grid data.
        </p>
      )}
      <p className="text-[11px] text-muted-foreground" data-testid="run-result-parameters">
        {params.length > 0 ? `Parameters used: ${params.map(([k, v]) => `${k} ${String(v)}`).join(', ')}.` : 'Parameters used: not reported by the backend.'}
      </p>
      <p className="text-[11px] text-muted-foreground" data-testid="run-result-set">
        Scenario set {result.scenario_set_id || 'not reported'}; registry version {result.registry_version || 'not reported'}.
      </p>
    </section>
  );
}
