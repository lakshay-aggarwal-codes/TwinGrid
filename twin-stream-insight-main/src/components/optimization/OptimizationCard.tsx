import { useEffect, useReducer, useRef } from 'react';
import { FlaskConical, ShieldAlert, Cpu } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { StatusMessage } from '@/components/shell/StatusMessage';
import { fetchOptimized, type OptimizeSummary } from '@/api/apiClient';
import { safeMessageFor } from '@/api/apiError';
import { useAuth } from '@/hooks/useAuth';
import { INITIAL_RUN, isModelUnavailable, optimizeReducer, optionalFlag, optionalText } from './optimizeRun';

interface Props {
  /** Lets the host (the Ops Console report) know the current completed summary, or null. */
  onSummaryChange?: (summary: OptimizeSummary | null) => void;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-mono text-foreground">{value}</dd>
    </div>
  );
}

/**
 * Experimental, simulator-only policy run (POST /api/optimize). Results are simulator output with NO evaluation
 * status: nothing here says the policy is better, safe or recommended, and no value is coloured by outcome.
 * The role check only disables the control (UX); the backend's 403 is still handled.
 */
export function OptimizationCard({ onSummaryChange }: Props) {
  const { role } = useAuth();
  const [run, dispatch] = useReducer(optimizeReducer, INITIAL_RUN);
  const controller = useRef<AbortController | null>(null);
  const isOperator = role === 'operator';

  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    onSummaryChange?.(run.status === 'completed' ? run.result.summary : null);
  }, [run, onSummaryChange]);

  const submit = () => {
    if (run.status !== 'confirming') return; // never a double submit
    dispatch({ type: 'submit' });
    const c = new AbortController();
    controller.current = c;
    fetchOptimized({}, c.signal)
      .then((result) => !c.signal.aborted && dispatch({ type: 'succeeded', result }))
      .catch((error) => !c.signal.aborted && dispatch({ type: 'failed', error }));
  };

  return (
    <section aria-label="Experimental policy run" className="rounded-md border border-border p-2.5 space-y-2" data-run-status={run.status}>
      <div className="flex items-center gap-1.5 text-xs text-foreground font-medium">
        <FlaskConical aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
        Policy run (PPO)
      </div>
      <p className="inline-block rounded border border-warning/50 px-1.5 py-px text-[9px] uppercase tracking-wider text-warning">
        Experimental · simulator-only · not evaluated
      </p>
      <p className="text-[10px] text-muted-foreground leading-snug">
        Runs the backend's trained policy inside the simulator via POST /api/optimize. The result is simulated, not measured,
        and has no evaluation status or baseline comparison. It is a backend request that is recorded in the audit log.
      </p>

      {run.status === 'idle' && (
        <>
          <Button size="sm" variant="secondary" className="w-full" disabled={!isOperator} aria-describedby="opt-role-note" onClick={() => dispatch({ type: 'request' })}>
            Run policy in simulator…
          </Button>
          {!isOperator && (
            <p id="opt-role-note" className="text-[10px] text-muted-foreground">
              Requires operator role
            </p>
          )}
        </>
      )}

      {run.status === 'confirming' && (
        <div className="space-y-1.5">
          <p className="text-[11px] flex items-center gap-1">
            <ShieldAlert aria-hidden="true" className="h-3 w-3 shrink-0" /> This will run an experimental 24 h policy in the simulator.
          </p>
          <div className="flex gap-1.5">
            <Button size="sm" className="flex-1" onClick={submit}>
              Confirm
            </Button>
            <Button size="sm" variant="ghost" className="flex-1" onClick={() => dispatch({ type: 'cancel' })}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {run.status === 'submitting' && <StatusMessage kind="loading">Waiting for response…</StatusMessage>}

      {run.status === 'failed' &&
        (isModelUnavailable(run) ? (
          <div role="status" className="flex items-start gap-1.5 text-xs text-muted-foreground">
            <Cpu aria-hidden="true" className="h-3.5 w-3.5 shrink-0 mt-px" />
            <span>
              <strong className="font-medium text-foreground">Model unavailable.</strong> The backend reports no valid model for this request.
              <button className="ml-2 underline underline-offset-2" onClick={() => dispatch({ type: 'reset' })}>
                Dismiss
              </button>
            </span>
          </div>
        ) : (
          <StatusMessage kind="error" action={{ label: 'Dismiss', onClick: () => dispatch({ type: 'reset' }) }}>
            {safeMessageFor(run.kind)}
            {run.kind === 'rate_limited' && run.retryAfterS !== undefined ? ` Retry after ${run.retryAfterS} s.` : ''}
          </StatusMessage>
        ))}

      {run.status === 'completed' && (
        <div role="status" aria-live="polite" className="space-y-1.5 text-[11px]" data-testid="optimize-result">
          <p className="text-muted-foreground">Simulator output — not evaluated, not compared with any baseline.</p>
          <dl className="space-y-1">
            <Row label="Mean PUE" value={run.result.summary.mean_pue.toFixed(2)} />
            <Row label="Mean WUE" value={run.result.summary.mean_wue.toFixed(3)} />
            <Row label="Mean cooling power" value={`${run.result.summary.mean_cooling_power_kw.toFixed(0)} kW`} />
            <Row label="Total water" value={`${Math.round(run.result.summary.total_water_consumed_L).toLocaleString()} L`} />
            <Row label="Internal training objective value" value={run.result.summary.total_reward.toFixed(1)} />
            <Row label="Safety violations (count reported by the run)" value={String(run.result.summary.safety_violations)} />
          </dl>
          <ul className="text-[10px] text-muted-foreground space-y-0.5">
            {optionalText(run.result, 'model_version') && <li>Model version: {optionalText(run.result, 'model_version')}</li>}
            {optionalText(run.result, 'physics_version') && <li>Physics version: {optionalText(run.result, 'physics_version')}</li>}
            {optionalFlag(run.result, 'experimental') !== null && <li>Experimental: {optionalFlag(run.result, 'experimental') ? 'yes' : 'no'}</li>}
          </ul>
          <Button size="sm" variant="outline" className="w-full" onClick={() => dispatch({ type: 'reset' })}>
            Run again
          </Button>
        </div>
      )}
    </section>
  );
}
