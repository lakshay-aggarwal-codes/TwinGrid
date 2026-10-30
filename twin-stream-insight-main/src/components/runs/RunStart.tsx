import { useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { StateBoundary, StateNotice } from '@/state/StateBoundary';
import { dataStateFromError } from '@/state/dataState';
import {
  controlText,
  initialValues,
  kindSupport,
  paramFields,
  runRequest,
  validateValues,
  weatherPlantText,
  type ParamValues,
} from '@/scenarios/model';
import { loadSelectedId, resolveSelection, saveSelectedId } from '@/scenarios/selection';
import type { ScenarioRegistry } from '@/scenarios/schema';
import { useScenarios } from '@/scenarios/useScenarios';
import { submitBodyOf } from '@/runs/model';
import { useSubmitRun } from '@/runs/useRun';
import { ScenarioParamForm } from '@/components/scenario/ScenarioParamForm';
import { ScenarioPicker } from '@/components/scenario/ScenarioPicker';
import { useRole } from '@/hooks/useAuth';
import { OPERATOR_REQUIRED_TEXT, isReadOnly } from '@/roleAccess';

function Configurator({ registry }: { registry: ScenarioRegistry }) {
  const navigate = useNavigate();
  const ids = useMemo(() => registry.scenarios.map((s) => s.id), [registry]);
  const [saved] = useState(() => loadSelectedId());
  const initial = resolveSelection(saved, ids);
  const restorable = initial.status === 'selected' && kindSupport(registry.scenarios.find((s) => s.id === initial.id)?.kind).supported;
  const [selectedId, setSelectedId] = useState<string | null>(restorable && initial.status === 'selected' ? initial.id : null);
  const [values, setValues] = useState<ParamValues>({});
  const submit = useSubmitRun();
  // A viewer is read-only: starting a run is locked (UX only; the server decides).
  const locked = isReadOnly(useRole().role);
  // Synchronous guard: two clicks in the same tick must not become two runs.
  const inFlight = useRef(false);

  const descriptor = registry.scenarios.find((s) => s.id === selectedId) ?? null;
  const { fields, unrecognised } = useMemo(() => (descriptor ? paramFields(descriptor) : { fields: [], unrecognised: [] }), [descriptor]);
  const effective = useMemo<ParamValues>(() => ({ ...initialValues(fields), ...values }), [fields, values]);
  const errors = useMemo(() => validateValues(fields, effective), [fields, effective]);
  const request = descriptor ? runRequest(descriptor, fields, effective) : null;
  const submitting = submit.isPending;

  const select = (id: string) => {
    setSelectedId(id);
    saveSelectedId(id);
    setValues({});
    submit.reset();
  };

  const onSubmit = () => {
    if (locked || request === null || inFlight.current) return;
    inFlight.current = true;
    submit.mutate(submitBodyOf(request), {
      onSuccess: (record) => navigate(`/runs/${encodeURIComponent(record.run_id)}`),
      onSettled: () => {
        inFlight.current = false;
      },
    });
  };

  return (
    <div className="space-y-3" data-testid="run-start">
      <p className="text-[11px] text-muted-foreground">
        Registry version {registry.registry_version}. A run is a simulated what-if queued on the backend; nothing is sent to a facility.
      </p>
      {initial.status === 'missing' && selectedId === null && (
        <StateNotice kind="stale" title="Selection not available" text="The previously selected scenario is no longer listed by the backend. Choose another." />
      )}
      <ScenarioPicker scenarios={registry.scenarios} selectedId={selectedId} onSelect={select} idPrefix="run-scenario" />

      {descriptor && kindSupport(descriptor.kind).supported && (
        <section aria-label="Run configuration" className="space-y-3">
          <ScenarioParamForm
            fields={fields}
            unrecognised={unrecognised}
            values={effective}
            errors={errors}
            idPrefix="run-param"
            disabled={locked}
            onChange={(name, value) => {
              setValues((v) => ({ ...v, [name]: value }));
              submit.reset();
            }}
          />
          <div className="rounded-md border border-border p-2 text-[11px] text-muted-foreground" data-testid="run-review">
            <p className="font-medium text-foreground">Review</p>
            <p>Scenario id: {descriptor.id}</p>
            <p>{weatherPlantText(descriptor)}</p>
            <p>{controlText(descriptor)}</p>
            <p>{request ? `Overrides sent: ${Object.keys(request).filter((k) => k !== 'scenario_id').join(', ') || 'none (backend preset)'}` : 'Fix the highlighted values to submit.'}</p>
          </div>
          <Button type="button" size="sm" disabled={request === null || submitting || locked} aria-describedby={locked ? 'run-locked-note' : undefined} onClick={onSubmit}>
            {submitting ? 'Submitting…' : 'Submit simulation run'}
          </Button>
          {locked && (
            <p id="run-locked-note" data-testid="run-locked-note" className="text-[11px] text-muted-foreground">
              {OPERATOR_REQUIRED_TEXT}. Starting a run is locked because TwinGrid is read-only for viewers.
            </p>
          )}
          {submitting && (
            <p role="status" className="text-xs text-muted-foreground" data-testid="run-submitting">
              Submitting… the backend has not accepted this run yet.
            </p>
          )}
          {submit.isError && <StateBoundary state={dataStateFromError(submit.error)} block={false}>{() => null}</StateBoundary>}
        </section>
      )}
    </div>
  );
}

/** Select → configure → submit. Submitting never shows a result: it navigates to the run, which starts as queued. */
export function RunStart() {
  const registry = useScenarios();
  return (
    <StateBoundary state={registry.state} onRetry={registry.refetch} block={false} messages={{ loading: 'Loading scenarios…', empty: 'The backend lists no scenarios.' }}>
      {(data) => <Configurator registry={data} />}
    </StateBoundary>
  );
}
