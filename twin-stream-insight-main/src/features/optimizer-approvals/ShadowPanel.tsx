import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/apiError";
import { StateBoundary } from "@/state/StateBoundary";
import { useApiQuery } from "@/state/useApiQuery";
import { fetchShadowSummary, postShadowSample, shadowKey } from "./api";
import { canPropose, shadowBars, type ShadowSummary } from "./model";

const BTN =
  "rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function Chart({ s }: { s: ShadowSummary }) {
  const b = shadowBars(s);
  if (b.total === 0) {
    return <p data-testid="shadow-empty" className="text-sm text-muted-foreground">{s.message ?? "No shadow samples have been recorded yet."}</p>;
  }
  const pct = (n: number) => `${((n / b.total) * 100).toFixed(1)}%`;
  return (
    <figure data-testid="shadow-chart" className="space-y-1">
      <div role="img" aria-label={`Of ${b.total} samples, the policy and the production rule chose the same cooling mode in ${b.agree} (${b.ratePct}%) and a different one in ${b.differ}.`} className="flex h-6 overflow-hidden rounded border border-border">
        <div className="flex items-center justify-center bg-muted text-[10px]" style={{ width: pct(b.agree) }}>
          {b.agree > 0 ? `same ${b.agree}` : ""}
        </div>
        <div className="flex items-center justify-center border-l border-dashed border-foreground/50 bg-background text-[10px]" style={{ width: pct(b.differ) }}>
          {b.differ > 0 ? `different ${b.differ}` : ""}
        </div>
      </div>
      <figcaption className="text-xs text-muted-foreground">
        Same cooling mode in {b.agree} of {b.total} samples ({b.ratePct}%). Different in {b.differ}.
        {s.period ? ` Samples from ${s.period.from} to ${s.period.to}.` : ""}
      </figcaption>
    </figure>
  );
}

/**
 * Shadow mode: the policy and the production rule are both asked what to do, and the two cooling-mode choices are compared.
 * Agreement says nothing about which is better: the page says so beside the chart.
 */
export function ShadowPanel({ role }: { role: string | null }) {
  const client = useQueryClient();
  const { state, refetch } = useApiQuery<ShadowSummary>({ queryKey: shadowKey, queryFn: ({ signal }) => fetchShadowSummary(signal), staleTime: 30_000 });
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function sample() {
    setBusy(true);
    setNote(null);
    try {
      await postShadowSample();
      setNote("One sample recorded.");
      void client.invalidateQueries({ queryKey: shadowKey });
    } catch (e) {
      setNote(
        e instanceof ApiError && e.kind === "unavailable"
          ? "No sample was recorded: there is no policy to shadow (503 model_unavailable)."
          : "The sample could not be recorded. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="shadow-h" className="space-y-2 rounded-md border border-border bg-card p-3">
      <h2 id="shadow-h" className="text-sm font-semibold">
        Shadow-mode comparison
      </h2>
      <p className="text-xs text-muted-foreground">
        Compares only the cooling mode the policy and the production rule would choose, on simulator state. Agreement does not mean either is better.
      </p>
      <StateBoundary state={state} onRetry={refetch} block={false}>
        {(s) => <Chart s={s} />}
      </StateBoundary>
      {canPropose(role) ? (
        <button type="button" className={BTN} disabled={busy} onClick={() => void sample()}>
          Record a shadow sample
        </button>
      ) : null}
      <div aria-live="polite" className="min-h-[1rem] text-xs">
        {note ? <span role="status">{note}</span> : null}
      </div>
    </section>
  );
}
