interface Props {
  label: string;
  /** A backend value, already formatted to the display precision from the unit table. Never a computed figure. */
  value: string | number;
  unit?: string;
  icon: React.ElementType;
  color?: string;
  /** The backend field this card shows (kept in the DOM so what is displayed can be audited). */
  field?: string;
}

/**
 * FE-08: one backend value. There is deliberately no trend arrow: a preview is computed for the current sidebar settings,
 * so the difference between two previews is a difference in inputs, not a trend over time.
 */
export function KpiCard({ label, value, unit, icon: Icon, color = 'text-primary', field }: Props) {
  return (
    <div className="card-grid-glow rounded-lg p-4 space-y-2" data-kpi-field={field}>
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground uppercase tracking-wider">{label}</span>
        <Icon className={`h-4 w-4 ${color} opacity-60`} aria-hidden="true" />
      </div>
      <div className="flex items-end gap-2">
        <span className="text-2xl font-bold font-mono text-foreground">{value}</span>
        {unit && <span className="text-sm text-muted-foreground mb-0.5">{unit}</span>}
      </div>
    </div>
  );
}
