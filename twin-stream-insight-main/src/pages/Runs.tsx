import { Link, useParams } from 'react-router-dom';
import { usePageTitle } from '@/hooks/usePageTitle';
import { isRunWorkflowEnabled } from '@/runs/flag';
import { RunMonitor } from '@/components/runs/RunMonitor';
import { RunStart } from '@/components/runs/RunStart';

/** `/runs` (select, configure, submit) and `/runs/:id` (monitor one run; the id in the URL lets a reload recover it). */
const Runs = () => {
  const { id } = useParams<{ id: string }>();
  usePageTitle(id ? 'TwinGrid — Run' : 'TwinGrid — New run');
  const enabled = isRunWorkflowEnabled();

  return (
    <main className="mx-auto h-full w-full max-w-3xl space-y-4 overflow-y-auto p-4">
      <header className="flex items-baseline justify-between gap-3">
        <h1 className="text-lg font-semibold text-foreground">{id ? 'Run' : 'New simulation run'}</h1>
        <Link to="/analytics" className="text-xs text-primary underline">
          Back to analytics
        </Link>
      </header>
      {!enabled ? (
        <p className="text-sm text-muted-foreground" data-testid="runs-disabled">
          The run workflow is turned off in this build. Previews on the analytics page are unaffected.
        </p>
      ) : id ? (
        <RunMonitor id={id} />
      ) : (
        <RunStart />
      )}
    </main>
  );
};

export default Runs;
