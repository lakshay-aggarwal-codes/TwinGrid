import { CARBON_FALLBACK_LABEL, DIRECTION_WORD, METRICS, fixed, signed, signedPct, type Delta, type MetricId } from "./metrics";

interface Props {
  deltas: Record<MetricId, Delta>;
  /** The scenario run's flag: false = its carbon figure uses the fallback intensity. */
  carbonIsReal: boolean;
  baselineCarbonIsReal: boolean;
}

/** Baseline, scenario and scenario - baseline for each metric. Direction is a glyph AND a word; there is no good/bad colouring (higher energy can be the point of a scenario). */
export function DeltaCards({ deltas, carbonIsReal, baselineCarbonIsReal }: Props) {
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4" data-testid="lab-delta-cards">
      {METRICS.map((m) => {
        const d = deltas[m.id];
        const dir = DIRECTION_WORD[d.direction];
        const unit = m.unit ? ` ${m.unit}` : "";
        return (
          <section key={m.id} aria-label={m.label} data-testid={`lab-card-${m.id}`} data-direction={d.direction} className="rounded-md border border-border bg-card p-3">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{m.label}</h3>
            <p className="text-2xl font-semibold tabular-nums text-foreground">
              {fixed(d.scenario, m.precision)}
              <span className="ml-1 text-xs font-normal text-muted-foreground">{m.unit}</span>
            </p>
            <p className="text-xs text-muted-foreground">Baseline {fixed(d.base, m.precision)}{unit}</p>
            <p className="mt-1 text-sm tabular-nums text-foreground">
              <span aria-hidden="true">{dir.glyph} </span>
              <span data-testid={`lab-delta-${m.id}`}>{signed(d.delta, m.precision)}{unit}</span>
              <span className="text-xs text-muted-foreground"> ({signedPct(d.pct)}) {dir.word}</span>
            </p>
            {m.id === "carbon" && (!carbonIsReal || !baselineCarbonIsReal) && (
              <p className="mt-1 rounded border border-dashed border-border px-1.5 py-0.5 text-[11px] text-muted-foreground" data-testid="lab-carbon-fallback">
                {CARBON_FALLBACK_LABEL}
                {!carbonIsReal && !baselineCarbonIsReal ? "." : carbonIsReal ? " (baseline only)." : " (scenario only)."}
              </p>
            )}
          </section>
        );
      })}
    </div>
  );
}
