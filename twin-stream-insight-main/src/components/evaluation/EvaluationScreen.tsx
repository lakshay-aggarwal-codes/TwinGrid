import { Link } from 'react-router-dom';
import { StateBoundary } from '@/state/StateBoundary';
import { useEvaluation, useEvaluationList } from '@/evaluation/useEvaluations';
import { EvaluationView } from './EvaluationView';

function EvaluationDetail({ id }: { id: string }) {
  const { state, refetch } = useEvaluation(id);
  return <StateBoundary state={state} onRetry={refetch}>{(result) => <EvaluationView result={result} />}</StateBoundary>;
}

/**
 * `/evaluation` shows the newest report the backend lists (its order, not ours); `/evaluation/:id` shows that one.
 * Report ids are links, never a ranking: the list order is the backend's.
 */
export function EvaluationScreen({ id }: { id?: string }) {
  const { state, refetch } = useEvaluationList();
  return (
    <StateBoundary state={state} onRetry={refetch} messages={{ not_run: 'No evaluation has been run: the backend lists no evaluation reports.' }}>
      {(list) => {
        const selected = id ?? list.evaluations[0].evaluation_id;
        return (
          <div className="space-y-4">
            {list.evaluations.length > 1 && (
              <nav aria-label="Evaluation reports" className="flex flex-wrap gap-2 text-xs">
                {list.evaluations.map((e) => (
                  <Link
                    key={e.evaluation_id}
                    to={`/evaluation/${encodeURIComponent(e.evaluation_id)}`}
                    aria-current={e.evaluation_id === selected ? 'page' : undefined}
                    className="rounded border border-border px-2 py-1 text-foreground underline-offset-2 hover:underline aria-[current=page]:font-semibold"
                  >
                    {e.evaluation_id}
                    {typeof e.outcome === 'string' && <span className="ml-1 text-muted-foreground">({e.outcome})</span>}
                  </Link>
                ))}
              </nav>
            )}
            <EvaluationDetail key={selected} id={selected} />
          </div>
        );
      }}
    </StateBoundary>
  );
}
