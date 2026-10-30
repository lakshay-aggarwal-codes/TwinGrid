import { useState } from "react";
import { StateBoundary } from "@/state/StateBoundary";
import type { UseApiQueryResult } from "@/state/useApiQuery";
import { inputsEqual, describeInputs, type LabInputs } from "./model";
import { METRICS, fixed, signed, type MetricId } from "./metrics";
import type { Sweep } from "./schema";
import { axisExtent, axisPos, tornadoRows } from "./tornadoRows";

interface Props {
  current: LabInputs;
  /** Inputs the sweep was requested for (null = not requested yet). */
  requestedFor: LabInputs | null;
  result: UseApiQueryResult<Sweep>;
  onRun: () => void;
  /** Read-only viewer: starting the sensitivity run is locked. */
  disabled?: boolean;
}

const W = 320;
const ROW_H = 26;

function Bars({ sweep, metric }: { sweep: Sweep; metric: MetricId }) {
  const m = METRICS.find((x) => x.id === metric)!;
  const rows = tornadoRows(sweep, metric);
  const extent = axisExtent(rows);
  return (
    <ol className="space-y-2" data-testid="lab-tornado-rows">
      {rows.map((r) => {
        const x1 = axisPos(r.min, extent) * W;
        const x2 = axisPos(r.max, extent) * W;
        return (
          <li key={r.parameter} data-testid={`lab-tornado-${r.parameter}`} className="space-y-0.5">
            <div className="flex items-baseline justify-between gap-2 text-xs">
              <span className="font-medium text-foreground">{r.label}</span>
              <span className="tabular-nums text-muted-foreground">swing {fixed(r.swing, m.precision)}{m.unit ? ` ${m.unit}` : ""}</span>
            </div>
            <svg viewBox={`0 0 ${W} ${ROW_H}`} className="h-7 w-full" role="img" aria-label={`${r.label}: ${r.points.map((p) => `${p.label} ${signed(p.delta, m.precision)}`).join(", ")}`}>
              <line x1={W / 2} x2={W / 2} y1={0} y2={ROW_H} stroke="currentColor" strokeWidth="1" className="text-muted-foreground" />
              <rect x={Math.min(x1, x2)} y={7} width={Math.max(2, Math.abs(x2 - x1))} height={12} fill="currentColor" className="text-primary/40" stroke="currentColor" strokeWidth="1" />
              {r.points.map((p) => {
                const x = axisPos(p.delta, extent) * W;
                // Non-colour cue: a triangle pointing the way the value moved, a bar for no change.
                return p.delta > 0 ? <path key={p.label} d={`M${x} 3 l4 6 h-8z`} fill="currentColor" /> : p.delta < 0 ? <path key={p.label} d={`M${x} 23 l4 -6 h-8z`} fill="currentColor" /> : <rect key={p.label} x={x - 1} y={4} width={2} height={18} fill="currentColor" />;
              })}
            </svg>
            <p className="text-[11px] text-muted-foreground">
              {r.points.map((p) => `${p.label}: ${signed(p.delta, m.precision)}${m.unit ? ` ${m.unit}` : ""}`).join(" · ")}
            </p>
          </li>
        );
      })}
    </ol>
  );
}

/** One-at-a-time sensitivity (backend sweep, at most 12 runs). Run on request: the endpoint is rate-limited. */
export function Tornado({ current, requestedFor, result, onRun, disabled = false }: Props) {
  const [metric, setMetric] = useState<MetricId>("energy");
  const stale = requestedFor !== null && !inputsEqual(requestedFor, current);
  return (
    <section aria-label="Sensitivity" className="space-y-3 rounded-md border border-border bg-card p-3" data-testid="lab-sensitivity">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">Sensitivity (one input at a time)</h2>
        <button type="button" onClick={onRun} disabled={disabled} className="rounded border border-border bg-background px-2.5 py-1 text-xs font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {requestedFor === null ? "Run sensitivity sweep" : stale ? "Re-run for current inputs" : "Re-run"}
        </button>
      </div>
      <p className="text-xs text-muted-foreground">
        Moves each input alone around the scenario (load ±10 points, ambient ±5 °C, setpoint ±2 °C, and each other cooling mode) and shows how much the metric changes. Interactions between inputs are not captured. At most 12 model runs; limited to 6 requests a minute.
      </p>
      {requestedFor === null ? (
        <p className="text-sm text-muted-foreground">Not run yet.</p>
      ) : (
        <StateBoundary state={result.state} onRetry={result.refetch} messages={{ loading: "Running the sensitivity sweep…" }}>
          {(sweep) => (
            <div className="space-y-3">
              {stale && (
                <p role="status" className="rounded border border-dashed border-border px-2 py-1 text-xs text-muted-foreground" data-testid="lab-sweep-stale">
                  These bars were computed for {describeInputs(requestedFor)}, not the inputs now selected.
                </p>
              )}
              <div role="radiogroup" aria-label="Metric" className="flex flex-wrap gap-1.5">
                {METRICS.map((m) => (
                  <button key={m.id} type="button" role="radio" aria-checked={metric === m.id} onClick={() => setMetric(m.id)} className={`rounded border px-2 py-1 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${metric === m.id ? "border-primary bg-primary/15 font-semibold underline" : "border-border bg-background hover:bg-muted"}`}>
                    {metric === m.id ? "✓ " : ""}{m.label}
                  </button>
                ))}
              </div>
              <Bars sweep={sweep} metric={metric} />
              <p className="text-[11px] text-muted-foreground" data-testid="lab-sweep-foot">
                Bars show variant minus baseline. {sweep.runs} of at most {sweep.max_runs} runs; {sweep.label}.
                {sweep.carbon_data_is_real ? "" : " CO₂ uses the fallback grid intensity, not real grid data."}
              </p>
            </div>
          )}
        </StateBoundary>
      )}
    </section>
  );
}
