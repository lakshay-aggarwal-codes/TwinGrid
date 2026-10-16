import { stripDescription, windowHours } from "./model";

interface Props {
  curve: readonly number[];
  best: { start_hour: number; end_hour: number } | null;
  durationH: number;
  /** Synthetic data is drawn dashed, so it can never be mistaken for data. */
  synthetic?: boolean;
}

/** 24 bars, one per site-local hour. The best window is outlined (not colour alone) and the text alternative says it. */
export function HourStrip({ curve, best, durationH, synthetic = false }: Props) {
  const lo = Math.min(...curve);
  const hi = Math.max(...curve);
  const span = hi - lo || 1;
  const inBest = best ? windowHours(best.start_hour, durationH) : new Set<number>();
  return (
    <div>
      <div role="img" aria-label={stripDescription(curve, best)} data-testid="hour-strip" data-synthetic={synthetic || undefined} className="flex h-16 items-end gap-px">
        {curve.map((v, h) => (
          <div
            key={h}
            data-hour={h}
            data-best={inBest.has(h) || undefined}
            style={{ height: `${20 + (80 * (v - lo)) / span}%` }}
            className={`flex-1 rounded-t-sm bg-muted-foreground/40 ${synthetic ? "border border-dashed border-muted-foreground" : ""} ${inBest.has(h) ? "outline outline-2 outline-primary" : ""}`}
          />
        ))}
      </div>
      <div aria-hidden="true" className="mt-0.5 flex justify-between text-[10px] text-muted-foreground">
        <span>00</span>
        <span>06</span>
        <span>12</span>
        <span>18</span>
        <span>23</span>
      </div>
    </div>
  );
}
