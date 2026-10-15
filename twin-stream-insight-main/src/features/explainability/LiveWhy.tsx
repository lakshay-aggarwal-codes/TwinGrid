import { liveWhy, featureLabel } from "./model";

/**
 * The detector's OWN per-signal reconstruction-error shares, as reported in the live frame while an anomaly episode is
 * open (`anomaly_status.explanation`). Renders nothing when the frame holds no usable explanation, so a missing
 * explanation is never shown as an empty or zero one. Each share is also a number in text; the bar is decoration.
 */
export function LiveWhy({ explanation }: { explanation: unknown }) {
  const why = liveWhy(explanation);
  if (!why) return null;
  return (
    <section aria-label="Why the detector flagged this" data-testid="live-why" className="w-full space-y-1 text-left">
      <h4 className="text-[11px] font-semibold text-foreground">Why it was flagged (detector's own breakdown, live)</h4>
      <ul className="space-y-1">
        {why.shares.map((s) => (
          <li key={s.feature} data-testid="live-why-row" className="text-[11px]">
            <div className="flex justify-between gap-2">
              <span className={s.feature === why.top ? "font-semibold" : ""}>
                {featureLabel(s.feature)}
                {s.feature === why.top ? " (largest share)" : ""}
              </span>
              <span className="font-mono tabular-nums">{s.pct.toFixed(1)}%</span>
            </div>
            <div aria-hidden="true" className="h-1 rounded bg-muted">
              <div className="h-1 rounded bg-foreground/60" style={{ width: `${Math.min(100, s.pct)}%` }} />
            </div>
          </li>
        ))}
      </ul>
      <p className="text-[10px] text-muted-foreground">
        Share of the reconstruction error each input contributed (not SHAP; synthetic-data detector).
        {why.totalError !== null ? ` Total error ${why.totalError.toFixed(4)}.` : ""}
      </p>
    </section>
  );
}
