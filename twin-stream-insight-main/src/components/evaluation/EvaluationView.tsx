import { useMemo } from 'react';
import { ProvenanceStrip, buildProvenance } from '@/provenance';
import { hardConstraintView, identityRows, outcomeView, pairedDifferences, tableView } from '@/evaluation/model';
import type { EvaluationResult } from '@/evaluation/schema';
import { EvaluationTable } from './EvaluationTable';
import { HardConstraintPanel } from './HardConstraintPanel';
import { OutcomeBanner } from './OutcomeBanner';
import { PairedDifferences } from './PairedDifferences';
import { PolicyComparison } from './PolicyComparison';

/** One backend `EvaluationResult`, rendered. Every number and sentence on this screen comes from the payload. */
export function EvaluationView({ result }: { result: EvaluationResult }) {
  const provenance = useMemo(
    () =>
      buildProvenance({
        source: { kind: 'evaluation' },
        origin: result.origin ?? null,
        // the physics that actually ran; the registered label is only a fallback for reports that predate the field
        physicsVersion: result.physics_version_executed ?? result.physics_version ?? null,
        evaluationStatus: result.decision.outcome,
        runId: result.evaluation_id,
        serverTime: result.generated_at_utc ?? null,
        // fallback carbon is a flag on the strip itself; absent carbon info is "not reported", not "real"
        inputsFallback: result.carbon?.is_real === undefined ? null : result.carbon.is_real ? [] : ['carbon'],
      }),
    [result],
  );
  const outcome = useMemo(() => outcomeView(result.decision, result.outcome_definitions), [result]);
  const table = useMemo(() => tableView(result.policies, result.metrics, result.carbon), [result]);
  const constraints = useMemo(() => hardConstraintView(result), [result]);
  const paired = useMemo(() => pairedDifferences(result.decision), [result]);
  const identity = useMemo(() => identityRows(result), [result]);

  return (
    <div className="space-y-4" data-testid="evaluation-view" data-evaluation-id={result.evaluation_id}>
      <ProvenanceStrip view={provenance} />
      <OutcomeBanner outcome={outcome} />
      <HardConstraintPanel view={constraints} />

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
      {/* keyed by report: a different report starts from its own defaults, never the previous selection */}
      <PolicyComparison key={result.evaluation_id} result={result} />
    </div>
  );
}
