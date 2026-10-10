import { useMemo } from 'react';
import { ProvenanceStrip, buildProvenance } from '@/provenance';
import { identityRows, outcomeView, pairedDifferences, tableView } from '@/evaluation/model';
import type { EvaluationResult } from '@/evaluation/schema';
import { EvaluationTable } from './EvaluationTable';
import { OutcomeBanner } from './OutcomeBanner';
import { PairedDifferences } from './PairedDifferences';

/** One backend `EvaluationResult`, rendered. Every number and sentence on this screen comes from the payload. */
export function EvaluationView({ result }: { result: EvaluationResult }) {
  const provenance = useMemo(
    () =>
      buildProvenance({
        source: { kind: 'evaluation' },
        origin: result.origin ?? null,
        physicsVersion: result.physics_version ?? null,
        evaluationStatus: result.decision.outcome,
      }),
    [result],
  );
  const outcome = useMemo(() => outcomeView(result.decision, result.outcome_definitions), [result]);
  const table = useMemo(() => tableView(result.policies, result.metrics, result.carbon), [result]);
  const paired = useMemo(() => pairedDifferences(result.decision), [result]);
  const identity = useMemo(() => identityRows(result), [result]);

  return (
    <div className="space-y-4" data-testid="evaluation-view" data-evaluation-id={result.evaluation_id}>
      <ProvenanceStrip view={provenance} />
      <OutcomeBanner outcome={outcome} />

      <dl className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-2" aria-label="Evaluation identity" data-testid="evaluation-identity">
        {identity.map((r) => (
          <div key={r.id} className="flex flex-wrap gap-x-2" data-identity={r.id} data-reported={r.reported}>
            <dt className="text-muted-foreground">{r.label}</dt>
            <dd className="break-all font-mono text-foreground">{r.value}</dd>
          </div>
        ))}
      </dl>

      {table.rows.length === 0 ? (
        <p className="text-xs text-muted-foreground" data-testid="no-policies">
          The backend returned no policies for this report.
        </p>
      ) : (
        <EvaluationTable view={table} />
      )}
      <PairedDifferences items={paired} ciLevel={result.ci_level} />
    </div>
  );
}
