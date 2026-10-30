import { COOLING_MODES, LAB_BOUNDS, describeInputs, snap, snapSetpoint, type FixedKey, type LabInputs, type SetpointRange } from "./model";

interface Props {
  inputs: LabInputs;
  /** The server's set-point range for the running physics. */
  range: SetpointRange;
  onChange: (next: LabInputs) => void;
  /** True while a newer setting is waiting out the debounce. */
  pending: boolean;
  /** Read-only viewer: every control is locked; the values stay visible. */
  disabled?: boolean;
}

type NumKey = FixedKey | "setpointC";
const FIELDS: { key: NumKey; label: string; hint: string }[] = [
  { key: "itLoadPct", label: "IT load", hint: "Share of server capacity in use, held for all 24 h" },
  { key: "ambientC", label: "Ambient temperature", hint: "Outside air temperature, held for all 24 h" },
  { key: "setpointC", label: "Cooling setpoint", hint: "Chilled-water temperature setpoint" },
];

/** Three sliders (each with a number box) and the cooling-mode radio group. Native inputs: keyboard and screen-reader behaviour come for free. */
export function Controls({ inputs, range, onChange, pending, disabled = false }: Props) {
  const boundsOf = (key: NumKey) => (key === "setpointC" ? range : LAB_BOUNDS[key]);
  const set = (key: NumKey, raw: number) =>
    !disabled &&
    onChange({ ...inputs, [key]: key === "setpointC" ? snapSetpoint(raw, range, inputs.setpointC) : snap(key, raw, inputs[key]) });
  return (
    <fieldset className="space-y-4 rounded-md border border-border bg-card p-3" data-testid="lab-controls">
      <legend className="px-1 text-sm font-semibold text-foreground">Scenario inputs</legend>
      {FIELDS.map((f) => {
        const b = boundsOf(f.key);
        const id = `lab-${f.key}`;
        return (
          <div key={f.key} className="space-y-1">
            <div className="flex items-baseline justify-between gap-2">
              <label htmlFor={id} className="text-sm text-foreground">{f.label}</label>
              <span className="flex items-center gap-1 text-sm tabular-nums">
                <input
                  type="number"
                  aria-label={`${f.label} value`}
                  disabled={disabled}
                  value={inputs[f.key]}
                  min={b.min}
                  max={b.max}
                  step={b.step}
                  onChange={(e) => e.target.value !== "" && set(f.key, Number(e.target.value))}
                  className="w-20 rounded border border-border bg-background px-1.5 py-0.5 text-right text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
                <span className="text-xs text-muted-foreground">{b.unit}</span>
              </span>
            </div>
            <input
              id={id}
              type="range"
              disabled={disabled}
              min={b.min}
              max={b.max}
              step={b.step}
              value={inputs[f.key]}
              onChange={(e) => set(f.key, Number(e.target.value))}
              aria-valuetext={`${inputs[f.key]} ${b.unit}`}
              className="h-2 w-full cursor-pointer accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <p className="text-[11px] text-muted-foreground">{f.hint} ({b.min} to {b.max} {b.unit})</p>
          </div>
        );
      })}
      <p className="text-[11px] text-muted-foreground" data-testid="lab-setpoint-source">
        Set-point range {range.min} to {range.max} {range.unit}: the range the evaluated controllers can command{range.physics ? ` under physics ${range.physics}` : ""}, read from the server.
      </p>
      <div role="radiogroup" aria-label="Cooling mode" className="space-y-1">
        <p className="text-sm text-foreground">Cooling mode</p>
        <div className="flex flex-wrap gap-1.5">
          {COOLING_MODES.map((m) => {
            const on = inputs.mode === m.id;
            return (
              <button
                key={m.id}
                type="button"
                role="radio"
                aria-checked={on}
                disabled={disabled}
                onClick={() => !disabled && onChange({ ...inputs, mode: m.id })}
                className={`rounded border px-2 py-1 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${on ? "border-primary bg-primary/15 font-semibold underline" : "border-border bg-background hover:bg-muted"}`}
              >
                {on ? "✓ " : ""}{m.label}
              </button>
            );
          })}
        </div>
      </div>
      <p role="status" className="text-[11px] text-muted-foreground" data-testid="lab-pending">
        {pending ? "Updating the estimate…" : `Showing: ${describeInputs(inputs)}.`}
      </p>
    </fieldset>
  );
}
