import { Ban, CheckCircle2, CircleHelp, Clock, Loader2, XCircle, type LucideIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { describeStatus, durationRows, failureText, timeRows, unrecognisedToken, type StatusId } from '@/runs/model';
import type { RunRecord } from '@/runs/schema';

/** Shape + text, never colour alone. Only the two non-final statuses animate, and only when motion is allowed. */
const ICON: Record<StatusId, { Icon: LucideIcon; spin: boolean }> = {
  queued: { Icon: Clock, spin: false },
  running: { Icon: Loader2, spin: true },
  completed: { Icon: CheckCircle2, spin: false },
  failed: { Icon: XCircle, spin: false },
  cancelled: { Icon: Ban, spin: false },
  unrecognised: { Icon: CircleHelp, spin: false },
};

const NOT_REPORTED = 'not reported';

interface Props {
  record: RunRecord;
  /** Offered only for an unrecognised status, where polling has stopped. */
  onCheckAgain?: () => void;
}

/**
 * The backend's own status for one run. There is deliberately no progress bar, percentage or ETA: the contract has
 * none. Elapsed figures are differences between backend timestamps. A job in this panel is never a result.
 */
export function RunStatusPanel({ record, onCheckAgain }: Props) {
  const view = describeStatus(record.status);
  const { Icon, spin } = ICON[view.id];
  const echoed = view.id === 'unrecognised' ? unrecognisedToken(record.status) : null;
  const params = Object.entries(record.parameters ?? {});
  return (
    <section aria-label="Run status" className="space-y-3 rounded-md border border-border p-3" data-testid="run-status" data-run-status={view.id}>
      {/* Announces the status on a transition only; timestamps and durations are not in this region. */}
      <p role="status" className="sr-only" data-testid="run-status-announcement">
        {`Run status: ${view.text}`}
      </p>
      <div className="flex items-center gap-2">
        <Icon aria-hidden="true" data-status-icon={view.id} className={spin ? 'h-4 w-4 motion-safe:animate-spin' : 'h-4 w-4'} />
        <span className="text-sm font-semibold text-foreground" data-testid="run-status-text">
          {view.text}
        </span>
        {echoed && <span className="text-xs text-muted-foreground">(received “{echoed}”)</span>}
      </div>
      <p className="text-xs text-muted-foreground">{view.description}</p>

      {view.id === 'failed' && (
        <p className="text-sm text-foreground" data-testid="run-failure">
          {failureText(record.failure_code)}
        </p>
      )}
      {view.id === 'unrecognised' && onCheckAgain && (
        <Button type="button" size="sm" variant="outline" onClick={onCheckAgain}>
          Check again
        </Button>
      )}

      <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-muted-foreground">Run id</dt>
        <dd className="font-mono break-all" data-testid="run-id">
          {record.run_id}
        </dd>
        <dt className="text-muted-foreground">Scenario id</dt>
        <dd className="font-mono break-all">{record.scenario_id}</dd>
        <dt className="text-muted-foreground">Scenario set id</dt>
        <dd className="font-mono break-all">{record.scenario_set_id || NOT_REPORTED}</dd>
        {timeRows(record).map((r) => (
          <div key={r.id} className="contents" data-time-row={r.id}>
            <dt className="text-muted-foreground">{r.label}</dt>
            <dd>{r.value}</dd>
          </div>
        ))}
        {durationRows(record).map((r) => (
          <div key={r.id} className="contents" data-duration-row={r.id}>
            <dt className="text-muted-foreground">{r.label}</dt>
            <dd>{r.value}</dd>
          </div>
        ))}
      </dl>

      {params.length > 0 && (
        <p className="text-[11px] text-muted-foreground" data-testid="run-parameters">
          Parameters used: {params.map(([k, v]) => `${k} ${String(v)}`).join(', ')}.
        </p>
      )}
    </section>
  );
}
