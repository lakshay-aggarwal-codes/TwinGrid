import { useMemo, useState } from 'react';
import { ProvenanceStrip, buildProvenance } from '@/provenance';
import { StateBoundary, StateNotice } from '@/state/StateBoundary';
import { describeInputs, WHATIF_METRICS } from '@/hooks/useWhatIf';
import type { WhatIfResponse } from '@/api/apiClient';
import { Button } from '@/components/ui/button';
import {
  controlText,
  initialValues,
  kindSupport,
  paramFields,
  runRequest,
  scenarioProvenance,
  validateValues,
  weatherPlantText,
  type ParamValues,
  type ScenarioRunRequest,
} from '@/scenarios/model';
import { isScenarioLibraryEnabled } from '@/scenarios/flag';
import { loadSelectedId, resolveSelection, saveSelectedId } from '@/scenarios/selection';
import type { ScenarioDescriptor, ScenarioRegistry } from '@/scenarios/schema';
import { useScenarioPreview, useScenarios } from '@/scenarios/useScenarios';
import { ScenarioPicker } from './ScenarioPicker';
import { ScenarioParamForm } from './ScenarioParamForm';

const NA = (
  <span title="Not available">
    <span aria-hidden="true">—</span>
    <span className="sr-only">not available</span>
  </span>
);

function Result({ descriptor, data }: { descriptor: ScenarioDescriptor; data: WhatIfResponse }) {
  const view = buildProvenance(scenarioProvenance(descriptor, data));
  return (
    <div className="space-y-2" data-testid="scenario-result">
      <ProvenanceStrip view={view} />
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full text-sm">
          <caption className="sr-only">Preview result for the selected scenario (simulated)</caption>
          <tbody>
            {WHATIF_METRICS.map((m) => {
              const v = m.pick(data);
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
      {!data.carbon_data_is_real && (
        <p className="text-[11px] text-muted-foreground" data-testid="scenario-fallback-carbon">
          CO₂ uses a fallback carbon intensity (a flat constant); the backend reports it is not real grid data.
        </p>
      )}
      <p className="text-[11px] text-muted-foreground" data-testid="scenario-inputs">
        {data.inputs ? `Inputs used: ${describeInputs(data.inputs)}.` : 'Inputs used: not reported by the backend.'}
      </p>
    </div>
  );
}

function Library({ registry }: { registry: ScenarioRegistry }) {
  const ids = useMemo(() => registry.scenarios.map((s) => s.id), [registry]);
  const [saved] = useState(() => loadSelectedId());
  const initial = resolveSelection(saved, ids);
  // A remembered scenario whose type this app does not support is not re-selected.
  const restorable = initial.status === 'selected' && kindSupport(registry.scenarios.find((s) => s.id === initial.id)?.kind).supported;
  const [selectedId, setSelectedId] = useState<string | null>(restorable && initial.status === 'selected' ? initial.id : null);
  const [values, setValues] = useState<ParamValues>({});
  const [submitted, setSubmitted] = useState<ScenarioRunRequest | null>(null);

  const descriptor = registry.scenarios.find((s) => s.id === selectedId) ?? null;
  const { fields, unrecognised } = useMemo(() => (descriptor ? paramFields(descriptor) : { fields: [], unrecognised: [] }), [descriptor]);
  // Values default from the descriptor until the person edits them (selection is remembered by id; edits are not).
  const effective = useMemo<ParamValues>(() => ({ ...initialValues(fields), ...values }), [fields, values]);
  const errors = useMemo(() => validateValues(fields, effective), [fields, effective]);
  const request = descriptor ? runRequest(descriptor, fields, effective) : null;
  const preview = useScenarioPreview(submitted);

  const select = (id: string) => {
    setSelectedId(id);
    saveSelectedId(id);
    setValues({});
    setSubmitted(null);
  };

  return (
    <div className="space-y-3" data-testid="scenario-library">
      <p className="text-[11px] text-muted-foreground">Registry version {registry.registry_version}. Scenarios are simulated previews; nothing is sent to a facility.</p>
      {initial.status === 'missing' && selectedId === null && (
        <StateNotice kind="stale" title="Selection not available" text="The previously selected scenario is no longer listed by the backend. Choose another." />
      )}
      <ScenarioPicker scenarios={registry.scenarios} selectedId={selectedId} onSelect={select} />

      {descriptor && kindSupport(descriptor.kind).supported && (
        <section aria-label="Scenario parameters" className="space-y-3">
          <ScenarioParamForm
            fields={fields}
            unrecognised={unrecognised}
            values={effective}
            errors={errors}
            onChange={(name, value) => {
              setValues((v) => ({ ...v, [name]: value }));
              setSubmitted(null);
            }}
          />
          <div className="rounded-md border border-border p-2 text-[11px] text-muted-foreground" data-testid="scenario-review">
            <p className="font-medium text-foreground">Review</p>
            <p>Scenario id: {descriptor.id}</p>
            <p>{weatherPlantText(descriptor)}</p>
            <p>{controlText(descriptor)}</p>
            <p>{request ? `Overrides sent: ${Object.keys(request).filter((k) => k !== 'scenario_id').join(', ') || 'none (backend preset)'}` : 'Fix the highlighted values to preview.'}</p>
          </div>
          <Button type="button" size="sm" disabled={request === null} onClick={() => setSubmitted(request)}>
            Preview scenario
          </Button>
          {submitted === null ? (
            <StateNotice kind="not_run" text="Nothing has been run yet. Choose “Preview scenario”." />
          ) : (
            <StateBoundary state={preview.state} onRetry={preview.refetch} block={false} messages={{ loading: 'Running preview…' }}>
              {(data) => <Result descriptor={descriptor} data={data} />}
            </StateBoundary>
          )}
        </section>
      )}
    </div>
  );
}

function Registry() {
  const registry = useScenarios();
  return (
    <StateBoundary state={registry.state} onRetry={registry.refetch} block={false} messages={{ loading: 'Loading scenarios…', empty: 'The backend lists no scenarios.' }}>
      {(data) => <Library registry={data} />}
    </StateBoundary>
  );
}

/** FE-15 scenario library. Renders nothing when the rollback flag is off, leaving the raw sliders as they were. */
export function ScenarioLibrary() {
  if (!isScenarioLibraryEnabled()) return null;
  return (
    <section aria-label="Scenario library" className="card-grid-glow space-y-3 rounded-lg p-4">
      <h3 className="text-sm font-semibold text-foreground">Scenario library</h3>
      <Registry />
    </section>
  );
}
