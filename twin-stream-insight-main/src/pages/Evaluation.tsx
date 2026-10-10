import { Link, useParams } from 'react-router-dom';
import { usePageTitle } from '@/hooks/usePageTitle';
import { isEvaluationViewEnabled } from '@/evaluation/flag';
import { EvaluationScreen } from '@/components/evaluation/EvaluationScreen';

/** `/evaluation` and `/evaluation/:id`: backend policy-evaluation reports (BC-11). PPO is one row among the baselines. */
const Evaluation = () => {
  const { id } = useParams<{ id: string }>();
  usePageTitle('TwinGrid — Policy evaluation');
  const enabled = isEvaluationViewEnabled();

  return (
    <main className="mx-auto h-full w-full max-w-5xl space-y-4 overflow-y-auto p-4">
      <header className="flex items-baseline justify-between gap-3">
        <h1 className="text-lg font-semibold text-foreground">Policy evaluation</h1>
        <Link to="/analytics" className="text-xs text-primary underline">
          Back to analytics
        </Link>
      </header>
      <p className="text-xs text-muted-foreground">Simulator results only. They describe policies run inside the simulator, not a real facility.</p>
      {enabled ? (
        <EvaluationScreen id={id} />
      ) : (
        <p className="text-sm text-muted-foreground" data-testid="evaluation-disabled">
          The evaluation view is turned off in this build.
        </p>
      )}
    </main>
  );
};

export default Evaluation;
