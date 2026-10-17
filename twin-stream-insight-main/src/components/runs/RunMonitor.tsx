import { Link } from 'react-router-dom';
import { StateBoundary, StateNotice } from '@/state/StateBoundary';
import { runStateOf, verifyResult } from '@/runs/model';
import type { RunRecord } from '@/runs/schema';
import { useRunResult, useRunStatus } from '@/runs/useRun';
import { RunResultPanel } from './RunResultPanel';
import { RunStatusPanel } from './RunStatusPanel';

const NOT_THIS_RUN_TEXT = 'The server sent a response that does not belong to this run. It is not shown.';

function RunView({ id, record, onRefresh }: { id: string; record: RunRecord; onRefresh: () => void }) {
  const state = runStateOf({ submitting: false, record, expectedId: id });
  const completed = state?.kind === 'status' && state.status === 'completed';
  // Nothing is requested until the backend says `completed`.
  const result = useRunResult(id, completed);

  if (state === null || state.kind === 'invalid_response') {
    return <StateNotice kind="unavailable" title="Run not shown" text={NOT_THIS_RUN_TEXT} block={false} />;
  }
  return (
    <div className="space-y-3">
      <RunStatusPanel record={record} onCheckAgain={onRefresh} />
      {completed && (
        <StateBoundary state={result.state} onRetry={result.refetch} block={false} messages={{ loading: 'Fetching the result…' }}>
          {(data) => {
            const verified = verifyResult(id, record, data);
            return verified.ok ? <RunResultPanel result={verified.result} /> : <StateNotice kind="unavailable" title="Result not shown" text={NOT_THIS_RUN_TEXT} block={false} />;
          }}
        </StateBoundary>
      )}
    </div>
  );
}

/** One run, by id from the URL: status (polled), then the result only after `completed` and a successful, verified fetch. */
export function RunMonitor({ id }: { id: string }) {
  const status = useRunStatus(id);
  return (
    <div className="space-y-3" data-testid="run-monitor">
      <StateBoundary state={status.state} onRetry={status.refetch} block={false} messages={{ loading: 'Loading run…' }}>
        {(record) => <RunView id={id} record={record} onRefresh={status.refetch} />}
      </StateBoundary>
      <p className="text-xs">
        <Link to="/runs" className="text-primary underline">
          Start a new run
        </Link>
      </p>
    </div>
  );
}
