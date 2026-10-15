import { useMemo } from "react";
import { AlertTriangle, Info, Sparkles } from "lucide-react";
import type { SlotWidgetProps } from "../types";
import { fmtSpan } from "./format";
import { RULE_BASED_LABEL, computeInsights, readiness, MIN_SAMPLES, MIN_SPAN_MS } from "./insights";
import { windowSamples } from "./liveSeries";
import { useGoals } from "./goalsStore";
import { useLiveSeries } from "./liveStore";
import { useOpenAlerts } from "./useExecData";

/** The look-back used by the trend rules. The window actually used is printed on every insight. */
export const INSIGHT_WINDOW_MS = 60 * 60_000;

export default function InsightsFeed(_props: SlotWidgetProps) {
  const all = useLiveSeries();
  const { goals } = useGoals();
  const alerts = useOpenAlerts();
  const samples = useMemo(() => windowSamples(all, INSIGHT_WINDOW_MS), [all]);
  const insights = useMemo(() => computeInsights({ samples, goals, alerts }), [samples, goals, alerts]);
  const ready = readiness(samples);

  return (
    <section aria-labelledby="exec-insights-heading" className="col-span-full space-y-2" data-testid="exec-insights">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="exec-insights-heading" className="inline-flex items-center gap-1.5 text-sm font-semibold text-foreground">
          <Sparkles aria-hidden="true" className="h-4 w-4" /> Insights
        </h2>
        <p className="rounded border border-dashed border-muted-foreground/50 px-1.5 py-0.5 text-[11px] text-muted-foreground">{RULE_BASED_LABEL} · no language model is called</p>
      </div>
      {!ready.ready && (
        <p role="status" className="text-xs text-muted-foreground" data-testid="insights-warming">
          Trend insights need at least {fmtSpan(MIN_SPAN_MS)} and {MIN_SAMPLES} live samples. This session has {ready.samples} sample{ready.samples === 1 ? "" : "s"} over {fmtSpan(ready.spanMs)}.
        </p>
      )}
      {insights.length === 0 ? (
        ready.ready && <p className="text-xs text-muted-foreground">No rule produced a statement for this window.</p>
      ) : (
        <ul className="space-y-2 p-0 m-0">
          {insights.map((i) => (
            <li key={i.id} className="card-grid-glow list-none rounded-lg p-3 space-y-1" data-insight={i.id} data-severity={i.severity}>
              <p className="flex items-start gap-1.5 text-sm text-foreground">
                {i.severity === "attention" ? <AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" /> : <Info aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />}
                <span>
                  {i.severity === "attention" && <strong className="mr-1 font-semibold">Needs attention:</strong>}
                  {i.text}
                </span>
              </p>
              <p className="text-[11px] text-muted-foreground">
                <span className="mr-2 rounded border border-border px-1 py-px">{RULE_BASED_LABEL}</span>
                Rule: {i.rule} · Data window: {i.window}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
