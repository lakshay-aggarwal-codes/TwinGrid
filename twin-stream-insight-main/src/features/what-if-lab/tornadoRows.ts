/** Task 15: tornado rows from the backend sweep. PURE. Bars show `variant - baseline` exactly as the backend computed them; nothing is re-simulated here. */
import type { MetricId } from "./metrics";
import { METRICS } from "./metrics";
import type { Sweep } from "./schema";

export interface TornadoPoint {
  readonly label: string;
  readonly delta: number;
}
export interface TornadoRow {
  readonly parameter: string;
  readonly label: string;
  readonly unit: string | null;
  readonly points: readonly TornadoPoint[];
  /** Most negative and most positive delta among the points (0 included so a one-sided bar still starts at the baseline). */
  readonly min: number;
  readonly max: number;
  /** max - min: the swing used to sort. */
  readonly swing: number;
}

const pointLabel = (parameter: string, direction: string, value: number | string, unit: string | null): string =>
  parameter === "mode" ? String(value).replace("_", " ") : `${direction === "low" ? "low" : "high"} ${value}${unit ? ` ${unit}` : ""}`;

/** Rows sorted by swing, largest first; ties by parameter name so the order is stable. */
export function tornadoRows(sweep: Sweep, metric: MetricId): TornadoRow[] {
  const key = METRICS.find((m) => m.id === metric)!.sweepKey;
  const rows: TornadoRow[] = sweep.parameters.map((p) => {
    const points = p.variants.map((v) => ({ label: pointLabel(p.parameter, v.direction, v.value, p.unit ?? null), delta: v.deltas[key] ?? 0 }));
    const deltas = [0, ...points.map((x) => x.delta)];
    const min = Math.min(...deltas);
    const max = Math.max(...deltas);
    return { parameter: p.parameter, label: p.label, unit: p.unit ?? null, points, min, max, swing: max - min };
  });
  return rows.sort((a, b) => b.swing - a.swing || a.parameter.localeCompare(b.parameter));
}

/** Symmetric axis half-width: the largest absolute delta (never 0, so an all-zero sweep still draws). */
export function axisExtent(rows: readonly TornadoRow[]): number {
  const m = Math.max(...rows.flatMap((r) => [Math.abs(r.min), Math.abs(r.max)]), 0);
  return m === 0 ? 1 : m;
}

/** Position 0..1 of a delta along a symmetric axis (0.5 = baseline). */
export const axisPos = (delta: number, extent: number): number => 0.5 + (delta / extent) * 0.5;
