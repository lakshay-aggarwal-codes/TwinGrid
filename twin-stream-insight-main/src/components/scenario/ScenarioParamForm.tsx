import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { ParamField, ParamValues } from '@/scenarios/model';

interface Props {
  fields: readonly ParamField[];
  unrecognised: readonly string[];
  values: ParamValues;
  errors: Readonly<Record<string, string>>;
  onChange: (name: string, value: string) => void;
  idPrefix?: string;
}

/** Form generated from the backend parameter schema. Bounds and options shown are the backend's; none are invented. */
export function ScenarioParamForm({ fields, unrecognised, values, errors, onChange, idPrefix = 'scenario-param' }: Props) {
  return (
    <div className="space-y-3" data-testid="scenario-param-form">
      {fields.map((f) => {
        const id = `${idPrefix}-${f.name}`;
        const err = errors[f.name];
        const describedBy = [f.description ? `${id}-desc` : null, err ? `${id}-err` : null].filter(Boolean).join(' ') || undefined;
        const bounds = f.kind === 'number' && (f.min !== null || f.max !== null) ? ` (${f.min ?? '…'} to ${f.max ?? '…'}${f.unit ? ` ${f.unit}` : ''})` : f.unit ? ` (${f.unit})` : '';
        return (
          <div key={f.name} className="space-y-1">
            <Label htmlFor={id} className="text-xs text-muted-foreground">
              {f.label}
              {bounds}
            </Label>
            {f.kind === 'enum' ? (
              <select
                id={id}
                value={values[f.name] ?? ''}
                onChange={(e) => onChange(f.name, e.target.value)}
                aria-invalid={err ? true : undefined}
                aria-describedby={describedBy}
                className="h-8 w-full rounded-md border border-border bg-muted px-2 text-sm"
              >
                {f.options.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            ) : (
              <Input
                id={id}
                type="number"
                inputMode="decimal"
                step="any"
                min={f.min ?? undefined}
                max={f.max ?? undefined}
                value={values[f.name] ?? ''}
                onChange={(e) => onChange(f.name, e.target.value)}
                aria-invalid={err ? true : undefined}
                aria-describedby={describedBy}
                className="h-8 bg-muted text-sm"
              />
            )}
            {f.description && (
              <p id={`${id}-desc`} className="text-[10px] text-muted-foreground">
                {f.description}
              </p>
            )}
            {err && (
              <p id={`${id}-err`} role="alert" className="text-[11px] text-destructive">
                {err}
              </p>
            )}
          </div>
        );
      })}
      {unrecognised.length > 0 && (
        <p className="text-[11px] text-muted-foreground" data-testid="scenario-unrecognised-params">
          Not shown (parameter type not recognised by this app): {unrecognised.join(', ')}. They keep the backend preset.
        </p>
      )}
    </div>
  );
}
