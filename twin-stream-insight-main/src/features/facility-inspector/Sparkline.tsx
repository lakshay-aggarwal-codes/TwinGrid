import type { Sparkline as SparklineModel } from "./readouts";

const W = 240;
const H = 48;
export const SPARK_SIZE = { width: W, height: H } as const;

/** A static SVG line. No animation, no state: it re-renders only when the history query changes. */
export function SparklineChart({ model, label }: { model: SparklineModel; label: string }) {
  const unit = model.unit ?? "";
  const summary = `${label}: ${model.goodCount} samples from ${model.fromLabel} to ${model.toLabel}; minimum ${model.min.toFixed(1)} ${unit}, maximum ${model.max.toFixed(1)} ${unit}, latest ${model.lastValue.toFixed(1)} ${unit}.`;
  return (
    <svg role="img" aria-label={summary} viewBox={`0 0 ${W} ${H}`} className="h-12 w-full text-primary" data-testid="sparkline">
      <line x1="0" y1={H - 0.5} x2={W} y2={H - 0.5} stroke="currentColor" strokeOpacity="0.2" strokeWidth="1" />
      {model.paths.map((d, i) => (
        <path key={i} d={d} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      ))}
      {model.last && model.paths.length > 0 && model.goodCount === 1 ? (
        <circle cx={model.last.x} cy={model.last.y} r="2.5" fill="currentColor" />
      ) : model.last ? (
        <rect x={model.last.x - 2} y={model.last.y - 2} width="4" height="4" fill="currentColor" />
      ) : null}
    </svg>
  );
}
