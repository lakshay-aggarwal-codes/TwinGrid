import { useId, useMemo, useState } from 'react';
import { CircleHelp, ShieldAlert, ShieldCheck, type LucideIcon } from 'lucide-react';
import { COMPARISON_MIN_POLICIES, comparisonView, defaultComparison, policyOptions, type ComparisonMetricRow } from '@/evaluation/comparison';
import { KNOWN_HARD_CONSTRAINTS, formatMetric, outcomeView, type PolicyConstraintState } from '@/evaluation/model';
import type { EvaluationResult } from '@/evaluation/schema';

const ICON: Record<PolicyConstraintState, LucideIcon> = { violated: ShieldAlert, clean: ShieldCheck, partial: CircleHelp };
const LABELS = new Map(KNOWN_HARD_CONSTRAINTS.map((k) => [k.id, k.label]));
const SELECT = 'rounded-md border border-border bg-background px-2 py-1 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

function MetricRows({ rows, group }: { rows: readonly ComparisonMetricRow[]; group: string }) {
  return (
    <>
      {rows.map((r) => (
        <tr key={r.id} data-cmp-row={r.id} data-cmp-group={group} className="border-b border-border last:border-0">
          <th scope="row" className="p-2 text-left font-mono font-medium text-foreground" title={r.definition ?? undefined}>
            {LABELS.get(r.id) ?? r.id}
          </th>
          <td className="p-2 font-mono text-foreground">{r.reference}</td>
          <td className="p-2 font-mono text-foreground">{r.compared}</td>
          <td className="p-2 font-mono text-foreground" data-cmp-diff>
            {r.difference ?? 'not provided'}
            {r.percent !== null && <span className="text-muted-foreground"> ({r.percent})</span>}
          </td>
          <td className="p-2 text-foreground" data-cmp-direction>
            {r.direction === null ? '—' : r.direction === 'same' ? 'same' : `compared is ${r.direction}`}
          </td>
          <td className="p-2 text-muted-foreground">{r.better === null ? 'not provided' : `${r.better} is better`}</td>
        </tr>
      ))}
    </>
  );
}

/**
 * Head-to-head view of two policies from ONE evaluation report. Hard constraints come first and decide eligibility;
 * reward and the other metrics follow as differences of means. There is no "winner" cell, no colour judgement and
 * no computed interval: the report's own outcome and its paired intervals (when it has them) are the only verdicts.
 */
export function PolicyComparison({ result }: { result: EvaluationResult }) {
  const uid = useId();
  const options = useMemo(() => policyOptions(result), [result]);
  const defaults = useMemo(() => defaultComparison(result), [result]);
  const [reference, setReference] = useState(defaults?.reference ?? '');
  const [compared, setCompared] = useState(defaults?.compared ?? '');
  const view = useMemo(() => comparisonView(result, reference, compared), [result, reference, compared]);
  const outcome = useMemo(() => outcomeView(result.decision, result.outcome_definitions), [result]);

  if (options.length < COMPARISON_MIN_POLICIES) {
    return (
      <section aria-label="Compare two policies" data-testid="policy-comparison" className="space-y-1 rounded-md border border-border p-3">
        <h2 className="text-sm font-semibold text-foreground">Compare two policies</h2>
        <p className="text-xs text-muted-foreground" data-testid="comparison-unavailable">
          This report has fewer than two policies, so there is nothing to compare.
        </p>
      </section>
    );
  }

  const { deciding } = view;
  return (
    <section aria-label="Compare two policies" data-testid="policy-comparison" className="space-y-3 rounded-md border border-border p-3">
      <h2 className="text-sm font-semibold text-foreground">Compare two policies</h2>
      <p className="text-xs text-muted-foreground">
        Both policies come from this report, so they were scored on the same scenarios. Hard constraints decide first. No overall verdict is given here: the outcome
        above is the report&apos;s only verdict. Simulated results only.
      </p>

      <div className="flex flex-wrap items-end gap-3">
        <label htmlFor={`${uid}-ref`} className="text-xs">
          <span className="block text-muted-foreground">Reference policy</span>
          <select id={`${uid}-ref`} className={SELECT} value={reference} onChange={(e) => setReference(e.target.value)}>
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.id}
                {o.kind && o.kind !== o.id ? ` (${o.kind})` : ''}
              </option>
            ))}
          </select>
        </label>
        <label htmlFor={`${uid}-cmp`} className="text-xs">
          <span className="block text-muted-foreground">Compared policy</span>
          <select id={`${uid}-cmp`} className={SELECT} value={compared} onChange={(e) => setCompared(e.target.value)}>
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.id}
                {o.kind && o.kind !== o.id ? ` (${o.kind})` : ''}
              </option>
            ))}
          </select>
        </label>
      </div>

      {!view.valid ? (
        <p role="status" className="text-xs text-foreground" data-testid="comparison-problem">
          {view.problem}
        </p>
      ) : (
        <>
          <div className="space-y-1 rounded-md border-2 border-border p-2" data-testid="comparison-constraints">
            <h3 className="text-xs font-semibold text-foreground">Hard constraints first</h3>
            <p className="text-xs text-foreground" data-testid="comparison-eligibility">
              {view.eligibility}
            </p>
            <ul className="space-y-0.5 text-xs text-foreground">
              {view.constraints.map((c) => {
                const Icon = ICON[c.state];
                return (
                  <li key={c.policyId} data-cmp-constraint={c.policyId} data-cmp-state={c.state} className="flex items-start gap-1.5">
                    <Icon aria-hidden="true" data-hc-icon={c.state} className="mt-px h-3.5 w-3.5 shrink-0" />
                    <span>
                      <span className="font-mono font-medium">{c.policyId}</span>: <span className={c.state === 'violated' ? 'font-semibold' : undefined}>{c.summary}</span>
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>

          <div className="space-y-0.5 text-xs text-foreground" data-testid="comparison-deciding">
            <h3 className="font-semibold">What decided the report&apos;s outcome</h3>
            <p>
              {outcome.headline}
              {outcome.reason !== null ? `. ${outcome.reason}` : ''}
            </p>
            <p className="text-muted-foreground">Decision rule: {outcome.definition}</p>
            {deciding.candidateWithinEnvelope === null ? (
              <p className="text-muted-foreground">This report has no PPO decision detail, so it names no outcome-deciding constraint.</p>
            ) : deciding.candidateWithinEnvelope ? (
              <p>The report&apos;s selected PPO candidate stayed within every counted hard limit on the test scenarios.</p>
            ) : (
              <p data-testid="comparison-candidate-violations">
                The report&apos;s selected PPO candidate violated:{' '}
                {deciding.candidateViolations.map((v) => `${LABELS.get(v.id) ?? v.id} (${formatMetric(v.steps)} steps/episode)`).join(', ') || 'a hard limit (not itemised)'}.
                That alone excludes outcome A, whatever its reward.
              </p>
            )}
            {deciding.unsafeBaselines.length > 0 && (
              <p>Baselines the report judged not envelope-safe: {deciding.unsafeBaselines.join(', ')}. They cannot be offered as a replacement controller.</p>
            )}
          </div>

          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Comparison table (scrollable)">
            <table className="w-full text-left text-xs" data-testid="comparison-table">
              <caption className="mb-1 text-left text-[11px] text-muted-foreground">
                Reference {view.referenceId} vs compared {view.comparedId}. Difference = compared minus reference, means over the test scenarios.
              </caption>
              <thead>
                <tr className="border-b border-border">
                  {['Metric', 'Reference', 'Compared', 'Difference', 'Direction', "The metric's own direction"].map((h) => (
                    <th key={h} scope="col" className="p-2 font-medium text-foreground">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <MetricRows rows={view.hardRows} group="hard" />
                <MetricRows rows={view.otherRows} group="other" />
              </tbody>
            </table>
          </div>

          <div className="space-y-0.5 text-xs" data-testid="comparison-uncertainty">
            <p className="text-muted-foreground">{view.sameScenarios}</p>
            <p className="text-foreground">{view.uncertaintyNote}</p>
            {view.uncertainty !== null && (
              <ul className="list-disc pl-4 font-mono text-foreground">
                {view.uncertainty.map((u) => (
                  <li key={u.scope}>
                    {u.scope} (n={u.n ?? 'not provided'}): {u.text}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  );
}
