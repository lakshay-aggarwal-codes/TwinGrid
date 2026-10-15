import { useReducer, useRef, useEffect } from "react";
import { fetchOptimized } from "@/api/apiClient";
import { safeMessageFor } from "@/api/apiError";
import { isModelUnavailable, INITIAL_RUN, optimizeReducer } from "@/components/optimization/optimizeRun";
import { ModelPassportButton } from "@/features/explainability/ModelPassportButton";
import { usePassport } from "@/features/explainability/usePassport";
import { canPropose, claimGate, ppoAvailability } from "./model";

const BTN =
  "rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** Whether the optimizer is unavailable, for the host page (the baseline card says so). */
export function usePpoState() {
  const { query } = usePassport();
  return { passport: query.data, passportFailed: query.isError };
}

export function PpoPanel({ role, onUnavailable }: { role: string | null; onUnavailable: (v: boolean) => void }) {
  const { passport, passportFailed } = usePpoState();
  const gate = claimGate(passport);
  const avail = ppoAvailability(passport);
  const [run, dispatch] = useReducer(optimizeReducer, INITIAL_RUN);
  const controller = useRef<AbortController | null>(null);
  const unavailable = run.status === "failed" && isModelUnavailable(run);

  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    onUnavailable(unavailable || (passport !== undefined && !avail.registryHasPromoted));
  }, [unavailable, passport, avail.registryHasPromoted, onUnavailable]);

  const submit = () => {
    dispatch({ type: "request" });
    dispatch({ type: "submit" });
    const c = new AbortController();
    controller.current = c;
    fetchOptimized({}, c.signal)
      .then((result) => !c.signal.aborted && dispatch({ type: "succeeded", result }))
      .catch((error) => !c.signal.aborted && dispatch({ type: "failed", error }));
  };

  return (
    <section aria-labelledby="ppo-h" className="space-y-2 rounded-md border border-border bg-card p-3" data-run-status={run.status}>
      <h2 id="ppo-h" className="text-sm font-semibold">
        PPO optimizer
      </h2>
      <p className="inline-block rounded border border-warning/50 px-1.5 py-px text-[10px] uppercase tracking-wider text-warning">
        Experimental · simulator-only
      </p>

      <div data-testid="claim-gate" data-allowed={gate.allowed ? "yes" : "no"} className="text-sm">
        {gate.allowed ? (
          <p>
            Stored evaluation decision, outcome {gate.outcome}: <q data-testid="claim-text">{gate.claimText}</q>
          </p>
        ) : (
          <p>
            No claim is made that PPO outperforms the baselines. The stored evaluation decision is{" "}
            <strong>{gate.outcome}</strong>
            {gate.reason ? `: ${gate.reason}` : "."}
          </p>
        )}
      </div>

      <p className="text-xs text-muted-foreground" data-testid="ppo-registry">
        {passport === undefined
          ? passportFailed
            ? "The model registry could not be read."
            : "Reading the model registry…"
          : avail.registryHasPromoted
            ? "The registry holds a promoted PPO policy the API may load."
            : `No promoted PPO policy in the registry${avail.statusText ? ` (newest entry: ${avail.statusText})` : ""}.`}
      </p>
      <ModelPassportButton kind="ppo" label="Optimizer passport" />

      {canPropose(role) ? (
        <button type="button" className={BTN} disabled={run.status === "submitting"} onClick={submit}>
          {run.status === "submitting" ? "Waiting for response…" : "Request a PPO run in the simulator"}
        </button>
      ) : (
        <p className="text-xs text-muted-foreground">Requesting a run needs the operator role.</p>
      )}

      {unavailable ? (
        <div role="alert" data-testid="ppo-unavailable" className="rounded-md border border-warning/50 p-2 text-sm">
          <p className="font-medium">The PPO optimizer is not available.</p>
          <p className="text-xs text-muted-foreground">
            The API answered 503 model_unavailable: it has no promoted policy that passed its integrity and compatibility checks.
            {avail.statusText ? ` Registry: ${avail.statusText}.` : ""} Nothing was run. The baseline recommendation below is shown instead.
          </p>
        </div>
      ) : null}
      {run.status === "failed" && !unavailable ? (
        <p role="alert" className="text-xs text-destructive">
          {safeMessageFor(run.kind)}
        </p>
      ) : null}
      {run.status === "completed" ? (
        <dl data-testid="ppo-result" className="space-y-0.5 text-xs">
          <p className="text-muted-foreground">Simulator output with no evaluation status; it is not a setpoint proposal.</p>
          {(
            [
              ["Mean PUE", run.result.summary.mean_pue.toFixed(3)],
              ["Mean WUE (L/kWh)", run.result.summary.mean_wue.toFixed(3)],
              ["Mean cooling power (kW)", run.result.summary.mean_cooling_power_kw.toFixed(1)],
              ["Water used (L)", run.result.summary.total_water_consumed_L.toFixed(0)],
              ["Safety violations", String(run.result.summary.safety_violations)],
            ] as const
          ).map(([k, v]) => (
            <div key={k} className="flex justify-between gap-2">
              <dt className="text-muted-foreground">{k}</dt>
              <dd className="font-mono">{v}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </section>
  );
}
