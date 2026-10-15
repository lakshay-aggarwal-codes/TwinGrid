import { buildSpark } from "./kpis";

const W = 120;
const H = 32;

/** A static SVG polyline of the values in order. Fewer than two points: a plain "collecting" note instead of a flat line. */
export function Spark({ values, label, unit }: { values: readonly number[]; label: string; unit: string }) {
  const m = buildSpark(values, W, H);
  if (!m) return <p className="text-[11px] text-muted-foreground">Trend: collecting live samples.</p>;
  const summary = `${label}: ${m.count} live samples this session; minimum ${m.min.toFixed(2)}${unit}, maximum ${m.max.toFixed(2)}${unit}, latest ${m.latest.toFixed(2)}${unit}.`;
  return (
    <div className="space-y-0.5">
    <svg role="img" aria-label={summary} viewBox={`0 0 ${W} ${H}`} className="h-8 w-full text-primary" data-testid="exec-spark">
      <line x1="0" y1={H - 0.5} x2={W} y2={H - 0.5} stroke="currentColor" strokeOpacity="0.2" strokeWidth="1" />
      <path d={m.path} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      <rect x={m.last.x - 2} y={m.last.y - 2} width="4" height="4" fill="currentColor" />
    </svg>
    <p className="text-[10px] text-muted-foreground">{label}, this session{unit ? ` (${unit.trim()})` : ""}</p>
    </div>
  );
}
