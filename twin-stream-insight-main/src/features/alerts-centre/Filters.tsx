import { SEVERITIES, STATUSES, STATUS_LABEL, toggleIn, type AlertStatus, type Filters as FilterState, type Severity } from "./model";

interface Props {
  value: FilterState;
  onChange: (next: FilterState) => void;
}

function Chip({ on, label, onClick }: { on: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={`rounded-full border px-2.5 py-1 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
        on ? "border-foreground bg-foreground text-background" : "border-border bg-background text-muted-foreground hover:bg-muted"
      }`}
    >
      {on ? "✓ " : ""}
      {label}
    </button>
  );
}

/** Severity and status filters. Pressed = included; none pressed = everything. The pressed state is shown by a tick, not colour alone. */
export function Filters({ value, onChange }: Props) {
  return (
    <div className="flex flex-wrap items-start gap-x-6 gap-y-2">
      <fieldset className="flex flex-wrap items-center gap-1.5">
        <legend className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Severity</legend>
        {SEVERITIES.map((s: Severity) => (
          <Chip key={s} on={value.severities.includes(s)} label={s} onClick={() => onChange({ ...value, severities: toggleIn(value.severities, s) })} />
        ))}
      </fieldset>
      <fieldset className="flex flex-wrap items-center gap-1.5">
        <legend className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Status</legend>
        {STATUSES.map((s: AlertStatus) => (
          <Chip key={s} on={value.statuses.includes(s)} label={STATUS_LABEL[s]} onClick={() => onChange({ ...value, statuses: toggleIn(value.statuses, s) })} />
        ))}
      </fieldset>
    </div>
  );
}
