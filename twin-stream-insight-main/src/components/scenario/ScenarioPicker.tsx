import { StateNotice } from '@/state/StateBoundary';
import { kindSupport, UNSUPPORTED_SCENARIO_TEXT, weatherPlantText } from '@/scenarios/model';
import type { ScenarioDescriptor } from '@/scenarios/schema';

interface Props {
  scenarios: readonly ScenarioDescriptor[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  idPrefix?: string;
}

/**
 * Descriptor list from the backend registry. Renders descriptor fields only; the weather/plant line is computed from
 * `weather_source` + `plant`, never from the scenario name. A kind this client does not know cannot be selected.
 */
export function ScenarioPicker({ scenarios, selectedId, onSelect, idPrefix = 'scenario' }: Props) {
  return (
    <fieldset className="space-y-2" data-testid="scenario-picker">
      <legend className="text-xs font-medium text-muted-foreground">Scenario</legend>
      {scenarios.map((s) => {
        const kind = kindSupport(s.kind);
        const inputId = `${idPrefix}-${s.id}`;
        return (
          <div key={s.id} className="rounded-md border border-border p-2" data-scenario-option={s.id}>
            <div className="flex items-start gap-2">
              <input
                type="radio"
                id={inputId}
                name={`${idPrefix}-choice`}
                className="mt-1"
                checked={selectedId === s.id}
                disabled={!kind.supported}
                aria-describedby={`${inputId}-meta`}
                onChange={() => onSelect(s.id)}
              />
              <label htmlFor={inputId} className="flex-1 text-sm text-foreground">
                {s.label}
              </label>
            </div>
            <div id={`${inputId}-meta`} className="ml-6 space-y-0.5 text-[11px] text-muted-foreground">
              <p data-scenario-kind>{kind.supported ? `Type: ${kind.text}` : UNSUPPORTED_SCENARIO_TEXT}</p>
              {s.description && <p>{s.description}</p>}
              <p data-scenario-weather-plant>{weatherPlantText(s)}</p>
              {!kind.supported && <StateNotice kind="unsupported_scenario" text={kind.raw ? `Scenario type "${kind.raw}" is not supported by this app.` : undefined} />}
            </div>
          </div>
        );
      })}
    </fieldset>
  );
}
