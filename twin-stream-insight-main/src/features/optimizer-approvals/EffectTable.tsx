import { PREDICTION_LABEL, effectRows, type Effect } from "./model";

/** Current settings vs proposed settings, from the twin. Direction is written as a word, never shown by colour alone. */
export function EffectTable({ effect, caption }: { effect: Effect; caption: string }) {
  const rows = effectRows(effect);
  return (
    <div className="space-y-1" data-testid="effect-table">
      <table className="w-full text-xs">
        <caption className="mb-1 text-left text-[11px] text-muted-foreground">
          {caption} · {PREDICTION_LABEL}
          {effect.hours ? ` · ${effect.hours} h at constant inputs` : ""}
        </caption>
        <thead>
          <tr className="text-left text-muted-foreground">
            <th scope="col" className="py-1 pr-2 font-medium">Metric</th>
            <th scope="col" className="py-1 pr-2 text-right font-medium">Current</th>
            <th scope="col" className="py-1 pr-2 text-right font-medium">Proposed</th>
            <th scope="col" className="py-1 text-right font-medium">Change</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-t border-border" data-metric={r.key}>
              <th scope="row" className="py-1 pr-2 text-left font-normal">
                {r.label}
                {r.unit ? <span className="text-muted-foreground"> ({r.unit})</span> : null}
              </th>
              <td className="py-1 pr-2 text-right font-mono">{r.reference}</td>
              <td className="py-1 pr-2 text-right font-mono">{r.proposed}</td>
              <td className="py-1 text-right font-mono">
                {r.delta} <span className="font-sans text-muted-foreground">({r.direction})</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[11px] text-muted-foreground">
        {effect.within_outlet_limit
          ? `The simulated outlet stays within the ${effect.outlet_limit_C} °C limit.`
          : `The simulated outlet exceeds the ${effect.outlet_limit_C} °C limit: this setting cannot be proposed.`}
        {effect.carbon_data_is_real ? "" : " Carbon uses a flat fallback intensity, not a real grid series."}
      </p>
    </div>
  );
}
