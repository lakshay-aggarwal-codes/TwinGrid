import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/apiError";
import { AuthRequiredError } from "@/authClient";
import { StateBoundary } from "@/state/StateBoundary";
import { useApiQuery } from "@/state/useApiQuery";
import { createProposal, fetchRecommendation, fetchSandbox, proposalsKey, recommendationKey } from "./api";
import { EffectTable } from "./EffectTable";
import {
  CHILLED_MAX_C,
  CHILLED_MIN_C,
  MAX_NOTE_CHARS,
  MODES,
  canPropose,
  modeLabel,
  proposalBody,
  recommendationQuery,
  setpointProblem,
  type Context,
  type Effect,
  type Mode,
  type Recommendation,
} from "./model";

const BTN =
  "rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function proposeErrorText(e: unknown): string {
  if (e instanceof AuthRequiredError) return "Your session has ended. Sign in again.";
  if (e instanceof ApiError) {
    if (e.kind === "forbidden") return "Only operators and admins can propose.";
    if (e.kind === "validation") return "Not accepted: an input is out of range, or the simulated outlet temperature would exceed its limit.";
    if (e.kind === "rate_limited") return "Too many requests. Try again shortly.";
  }
  return "The request could not be completed. Try again.";
}

function Body({ rec, ctx, role }: { rec: Recommendation; ctx: Context; role: string | null }) {
  const client = useQueryClient();
  const sel = rec.recommendation.selected;
  const [chilled, setChilled] = useState(sel ? String(sel.chilled_water_temp_C) : "");
  const [mode, setMode] = useState<string>(sel?.cooling_mode ?? "hybrid");
  const [sandbox, setSandbox] = useState<Effect | null>(null);
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // A new recommendation (the inputs changed) replaces the editable set-points and drops a stale sandbox result.
  useEffect(() => {
    setChilled(sel ? String(sel.chilled_water_temp_C) : "");
    setMode(sel?.cooling_mode ?? "hybrid");
    setSandbox(null);
  }, [sel?.chilled_water_temp_C, sel?.cooling_mode]); // eslint-disable-line react-hooks/exhaustive-deps

  const setpoints = { chilled_water_temp_c: Number(chilled), cooling_mode: mode as Mode };
  const problem = chilled.trim() === "" ? "Enter a chilled-water temperature." : setpointProblem(setpoints);
  const edited = sel !== null && (Number(chilled) !== sel.chilled_water_temp_C || mode !== sel.cooling_mode);

  async function run<T>(work: () => Promise<T>, done: (v: T) => void) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      done(await work());
    } catch (e) {
      setError(proposeErrorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      {sel ? (
        <>
          <p data-testid="recommendation-source" className="text-sm">
            <strong>{sel.name.toUpperCase()} baseline controller</strong> proposes{" "}
            <strong>{sel.chilled_water_temp_C.toFixed(1)} °C</strong> chilled water and <strong>{modeLabel(sel.cooling_mode)}</strong> cooling.
          </p>
          <p className="text-xs text-muted-foreground">
            Basis: {sel.basis}. Stored validation reward {sel.validation_reward.toFixed(2)} (config {sel.config}). {rec.recommendation.note}
          </p>
          {rec.predicted ? <EffectTable effect={rec.predicted} caption="Recommended set-points vs your current settings" /> : null}

          <fieldset className="space-y-2 rounded-md border border-border p-2">
            <legend className="px-1 text-[11px] uppercase tracking-wider text-muted-foreground">Sandbox: try set-points (nothing is saved)</legend>
            <div className="flex flex-wrap items-end gap-3">
              <label className="text-xs">
                <span className="block text-muted-foreground">Chilled water ({CHILLED_MIN_C} to {CHILLED_MAX_C} °C)</span>
                <input
                  type="number"
                  step="0.5"
                  min={CHILLED_MIN_C}
                  max={CHILLED_MAX_C}
                  value={chilled}
                  onChange={(e) => setChilled(e.target.value)}
                  className="w-24 rounded-md border border-border bg-background px-2 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </label>
              <label className="text-xs">
                <span className="block text-muted-foreground">Cooling mode</span>
                <select
                  value={mode}
                  onChange={(e) => setMode(e.target.value)}
                  className="rounded-md border border-border bg-background px-2 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {MODES.map((m) => (
                    <option key={m} value={m}>
                      {modeLabel(m)}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className={BTN}
                disabled={busy || problem !== null}
                onClick={() => void run(() => fetchSandbox(ctx, setpoints), (r) => setSandbox(r.predicted))}
              >
                Run in sandbox
              </button>
            </div>
            {problem ? <p className="text-xs text-muted-foreground">{problem}</p> : null}
            {edited ? <p className="text-xs text-muted-foreground">These set-points differ from the controller's, so a proposal is recorded as manual.</p> : null}
            {sandbox ? <EffectTable effect={sandbox} caption="Sandbox result" /> : null}
          </fieldset>

          {canPropose(role) ? (
            <div className="space-y-1.5">
              <label htmlFor="proposal-rationale" className="block text-xs text-muted-foreground">
                Why (optional, up to {MAX_NOTE_CHARS} characters)
              </label>
              <textarea
                id="proposal-rationale"
                rows={2}
                maxLength={MAX_NOTE_CHARS}
                value={rationale}
                onChange={(e) => setRationale(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <button
                type="button"
                className={BTN}
                disabled={busy || problem !== null}
                onClick={() =>
                  void run(
                    () => createProposal(proposalBody(ctx, setpoints, rationale)),
                    (p) => {
                      setMessage(`Proposal #${p.id} is waiting for an admin's decision.`);
                      setRationale("");
                      void client.invalidateQueries({ queryKey: proposalsKey });
                    },
                  )
                }
              >
                Propose for approval
              </button>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">Proposing needs the operator role.</p>
          )}
          <div aria-live="polite" className="min-h-[1rem] text-xs">
            {message ? <span role="status">{message}</span> : null}
            {error ? (
              <span role="alert" className="text-destructive">
                {error}
              </span>
            ) : null}
          </div>
        </>
      ) : (
        <div data-testid="no-baseline" className="space-y-1 text-sm">
          <p>No baseline controller can make a recommendation right now.</p>
          <ul className="list-disc pl-5 text-xs text-muted-foreground">
            {rec.recommendation.considered.map((c) => (
              <li key={c.name}>
                {c.name}: {c.reason ?? "not usable"}
              </li>
            ))}
          </ul>
        </div>
      )}
      {sel && rec.recommendation.considered.some((c) => !c.usable) ? (
        <ul className="list-disc pl-5 text-[11px] text-muted-foreground">
          {rec.recommendation.considered
            .filter((c) => !c.usable)
            .map((c) => (
              <li key={c.name}>
                {c.name} not used: {c.reason}
              </li>
            ))}
        </ul>
      ) : null}
    </div>
  );
}

export function RecommendationCard({ ctx, role, ppoUnavailable }: { ctx: Context; role: string | null; ppoUnavailable: boolean }) {
  const query = recommendationQuery(ctx);
  const { state, refetch } = useApiQuery<Recommendation>({
    queryKey: recommendationKey(query),
    queryFn: ({ signal }) => fetchRecommendation(ctx, signal),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
  return (
    <section aria-labelledby="rec-h" className="space-y-2 rounded-md border border-border bg-card p-3">
      <h2 id="rec-h" className="text-sm font-semibold">
        Baseline controller recommendation
      </h2>
      <p className="text-xs text-muted-foreground">
        From the stored rule and PID baseline controllers, not from PPO.
        {ppoUnavailable ? " The PPO optimizer is unavailable, so this is the recommendation shown." : ""}
      </p>
      <StateBoundary state={state} onRetry={refetch} block={false}>
        {(rec) => <Body rec={rec} ctx={ctx} role={role} />}
      </StateBoundary>
    </section>
  );
}
