import type { HealthSensor } from "./schema";

/** A tiny trend line. Static (no animation); the text next to it carries the same information. */
export function Sparkline({ series, label }: { series: HealthSensor["series"]; label: string }) {
  if (series.length < 2) return <span className="text-[11px] text-muted-foreground">no trend line</span>;
  const w = 120;
  const h = 28;
  const values = series.map((p) => p.v);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const pts = series.map((p, i) => `${((i / (series.length - 1)) * w).toFixed(1)},${(h - 2 - ((p.v - lo) / span) * (h - 4)).toFixed(1)}`).join(" ");
  return (
    <svg role="img" aria-label={label} viewBox={`0 0 ${w} ${h}`} className="h-7 w-[120px] text-foreground">
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
