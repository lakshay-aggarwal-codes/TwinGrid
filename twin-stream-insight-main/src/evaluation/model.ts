/**
 * FE-17: pure view-model for an `EvaluationResult` (roadmap §9.2). No React, no clock, no network.
 *
 * The UI renders what the backend sent. This module formats; it never scores, ranks, sorts, differences or estimates
 * anything. Row order is the backend's `policies` order; columns are the metrics the backend actually reported;
 * outcome/claim text is the backend's, verbatim; a value the backend did not send is shown as "not provided".
 */
import type { EvaluationDecision, EvaluationPolicy, EvaluationResult, MetricDefinition } from './schema';

export const NOT_PROVIDED = 'not provided';
export const DEFINITION_NOT_PROVIDED = 'definition not provided';
export const UNCERTAINTY_NOT_PROVIDED = 'uncertainty not provided';

// ------------------------------------------------------------------------------------------------ outcome

export type OutcomeKind = 'A' | 'B' | 'C' | 'NOT_EVALUATED' | 'unrecognised';

export interface OutcomeView {
  readonly kind: OutcomeKind;
  /** The backend's code, exactly as received. */
  readonly code: string;
  readonly headline: string;
  /** Backend-supplied definition text, or "definition not provided". Never written by the frontend. */
  readonly definition: string;
  readonly definitionProvided: boolean;
  /** `decision.claim_allowed`, verbatim. */
  readonly claimAllowed: string;
  /** `decision.reason`, verbatim, or null when the backend sent none. */
  readonly reason: string | null;
}

function classifyOutcome(code: string): OutcomeKind {
  return code === 'A' || code === 'B' || code === 'C' || code === 'NOT_EVALUATED' ? code : 'unrecognised';
}

/**
 * Every outcome gets the same structure. A/B/C meanings are shown only when the backend supplies them in
 * `outcome_definitions`; `NOT_EVALUATED` has no backend definition today, so it shows "definition not provided".
 */
export function outcomeView(decision: EvaluationDecision, definitions: Readonly<Record<string, string>> | undefined): OutcomeView {
  const kind = classifyOutcome(decision.outcome);
  const supplied = kind === 'A' || kind === 'B' || kind === 'C' ? definitions?.[kind] : undefined;
  const definitionProvided = typeof supplied === 'string' && supplied.trim() !== '';
  const headline =
    kind === 'NOT_EVALUATED'
      ? `Not evaluated — claim allowed: ${decision.claim_allowed}`
      : kind === 'unrecognised'
        ? `Unrecognised outcome: ${decision.outcome}`
        : `Outcome class ${kind}`;
  return {
    kind,
    code: decision.outcome,
    headline,
    definition: definitionProvided ? (supplied as string) : DEFINITION_NOT_PROVIDED,
    definitionProvided,
    claimAllowed: decision.claim_allowed,
    reason: typeof decision.reason === 'string' && decision.reason !== '' ? decision.reason : null,
  };
}

// ------------------------------------------------------------------------------------------------ table

/** Display only: rounds to 6 significant digits; the exact value goes in the cell's title. No precision is added. */
export function formatMetric(value: number): string {
  return value.toLocaleString('en-US', { maximumSignificantDigits: 6 });
}

export interface ColumnView {
  readonly id: string;
  /** The backend's `better` field as a hint ("lower is better"), or null when not supplied. Never used to rank. */
  readonly hint: string | null;
  readonly definition: string | null;
  /** Set on carbon columns when the backend says the carbon data is not real (or does not say). */
  readonly caveat: string | null;
}

export interface CellView {
  readonly text: string;
  readonly exact: string | null;
}

export interface RowView {
  readonly policyId: string;
  readonly kind: string | null;
  readonly cells: readonly CellView[];
}

export interface TableView {
  readonly columns: readonly ColumnView[];
  readonly rows: readonly RowView[];
}

function hintFor(def: MetricDefinition | undefined): string | null {
  const better = def?.better;
  if (better === 'lower') return 'lower is better';
  if (better === 'higher') return 'higher is better';
  return typeof better === 'string' && better !== '' ? `better: ${better}` : null;
}

function carbonCaveat(carbon: EvaluationResult['carbon']): string {
  if (carbon === undefined || carbon.is_real === undefined) return 'carbon data source not reported';
  if (carbon.is_real) return '';
  return carbon.flat_curve === true ? 'Fallback carbon (flat constant)' : 'Fallback carbon values (not real carbon data)';
}

/** Rows = backend `policies`, in backend order. Columns = metric ids in order of first appearance. Nothing is sorted. */
export function tableView(
  policies: readonly EvaluationPolicy[],
  metrics: Readonly<Record<string, MetricDefinition>> | undefined,
  carbon: EvaluationResult['carbon'],
): TableView {
  const ids: string[] = [];
  for (const p of policies) for (const id of Object.keys(p.metrics)) if (!ids.includes(id)) ids.push(id);

  const columns: ColumnView[] = ids.map((id) => {
    const caveat = /carbon/i.test(id) ? carbonCaveat(carbon) : '';
    return {
      id,
      hint: hintFor(metrics?.[id]),
      definition: metrics?.[id]?.definition ?? null,
      caveat: caveat === '' ? null : caveat,
    };
  });

  const rows: RowView[] = policies.map((p) => ({
    policyId: p.policy_id,
    kind: p.kind ?? null,
    cells: ids.map((id) => {
      const v = p.metrics[id];
      return typeof v === 'number' ? { text: formatMetric(v), exact: String(v) } : { text: NOT_PROVIDED, exact: null };
    }),
  }));
  return { columns, rows };
}

// ------------------------------------------------------------------------------------------------ paired differences

export interface PairedDifferenceView {
  readonly baseline: string;
  readonly scope: 'training seeds' | 'test scenarios';
  readonly n: number | null;
  /** `mean [lo, hi]` exactly as sent, or "uncertainty not provided" when any of the three is missing. Never imputed. */
  readonly text: string;
  readonly provided: boolean;
}

const SCOPES: ReadonlyArray<readonly ['seed_level_diff' | 'scenario_level_diff', PairedDifferenceView['scope']]> = [
  ['seed_level_diff', 'training seeds'],
  ['scenario_level_diff', 'test scenarios'],
];

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}
function finiteOrNull(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

/**
 * CIs exist in this backend ONLY as paired PPO-minus-baseline differences inside `decision.detail.per_baseline`
 * (G-EVAL.md). They are read, never computed. Without PPO candidates there is nothing to read and the list is empty.
 */
export function pairedDifferences(decision: EvaluationDecision): PairedDifferenceView[] {
  const detail = decision.detail;
  const perBaseline = isRecord(detail) ? detail.per_baseline : undefined;
  if (!isRecord(perBaseline)) return [];
  const out: PairedDifferenceView[] = [];
  for (const [baseline, entry] of Object.entries(perBaseline)) {
    if (!isRecord(entry)) continue;
    for (const [key, scope] of SCOPES) {
      const diff = entry[key];
      if (!isRecord(diff)) continue;
      const mean = finiteOrNull(diff.mean);
      const lo = finiteOrNull(diff.ci_low);
      const hi = finiteOrNull(diff.ci_high);
      const provided = mean !== null && lo !== null && hi !== null;
      out.push({
        baseline,
        scope,
        n: finiteOrNull(diff.n),
        text: provided ? `${formatMetric(mean)} [${formatMetric(lo)}, ${formatMetric(hi)}]` : UNCERTAINTY_NOT_PROVIDED,
        provided,
      });
    }
  }
  return out;
}

export function ciLevelText(level: number | undefined): string {
  return level === undefined ? 'level not provided' : `level ${level}`;
}

// ------------------------------------------------------------------------------------------------ identity strip

export interface IdentityRow {
  readonly id: string;
  readonly label: string;
  readonly value: string;
  readonly reported: boolean;
}

function row(id: string, label: string, value: string | undefined | null): IdentityRow {
  return value === undefined || value === null || value === ''
    ? { id, label, value: NOT_PROVIDED, reported: false }
    : { id, label, value, reported: true };
}

/**
 * Two ids are named apart on purpose (G-EVAL.md): this is the *evaluation* scenario set (a hash of the pre-registered
 * evaluation episodes), not the BC-09 *scenario registry* set shown on run pages.
 */
export function identityRows(r: EvaluationResult): IdentityRow[] {
  const sets = r.scenario_sets ?? {};
  const setText = (k: string) => (sets[k] ? `${sets[k].id} (n=${sets[k].n})` : null);
  return [
    row('evaluation-scenario-set', 'Evaluation scenario set', r.scenario_set_id),
    row('validation-set', 'Validation episodes', setText('validation')),
    row('test-set', 'Test episodes', setText('test')),
    row('prereg', 'Pre-registration hash (sha256)', r.preregistration_sha256),
    row('physics', 'Physics version', r.physics_version),
    row('scenario-inputs', 'Scenario inputs', r.scenario_inputs),
    // The backend sends no dataset identity for evaluations; the row stays visible as "not provided".
    row('dataset', 'Dataset identity', null),
    row('generated', 'Report generated (server time, UTC)', r.generated_at_utc),
  ];
}
