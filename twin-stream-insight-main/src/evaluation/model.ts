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

/** Like `row`, but a missing value reads `missingText` (more specific than "not provided") and stays `reported: false`. */
function rowOr(id: string, label: string, value: string | null, missingText: string): IdentityRow {
  return value === null || value === '' ? { id, label, value: missingText, reported: false } : { id, label, value, reported: true };
}

/**
 * Two ids are named apart on purpose (G-EVAL.md): this is the *evaluation* scenario set (a hash of the pre-registered
 * evaluation episodes), not the BC-09 *scenario registry* set shown on run pages.
 */
export function identityRows(r: EvaluationResult): IdentityRow[] {
  const sets = r.scenario_sets ?? {};
  const setText = (k: string) => (sets[k] ? `${sets[k].id} (n=${sets[k].n})` : null);
  return [
    row('evaluation-id', 'Evaluation id', r.evaluation_id),
    row('evaluation-scenario-set', 'Evaluation scenario set', r.scenario_set_id),
    row('validation-set', 'Validation episodes', setText('validation')),
    row('test-set', 'Test episodes', setText('test')),
    row('prereg', 'Pre-registration hash (sha256)', r.preregistration_sha256),
    rowOr('physics-executed', 'Physics executed', r.physics_version_executed === undefined ? null : physicsExecutedText(r), PHYSICS_EXECUTED_NOT_REPORTED),
    row('physics', 'Physics label (as registered)', r.physics_version),
    rowOr('carbon', 'Carbon signal', r.carbon?.is_real === undefined ? null : carbonText(r.carbon), 'not reported'),
    row('scenario-inputs', 'Scenario inputs', r.scenario_inputs),
    // The backend sends no dataset identity for evaluations; the row stays visible as "not provided".
    row('dataset', 'Dataset identity', null),
    row('generated', 'Report generated (server time, UTC)', r.generated_at_utc),
  ];
}


// ------------------------------------------------------------------------------------------------ physics and carbon

export const PHYSICS_EXECUTED_NOT_REPORTED = 'not reported (written before the executed physics was recorded)';

/** The physics the environment ran. When the registered label says something else, both are shown, never merged. */
export function physicsExecutedText(r: EvaluationResult): string {
  const executed = r.physics_version_executed;
  if (executed === undefined || executed === '') return PHYSICS_EXECUTED_NOT_REPORTED;
  return r.physics_version !== undefined && r.physics_version !== executed ? `${executed} (registered as "${r.physics_version}")` : executed;
}

/** Measured / assumed carbon, from the backend's own flags. Absent flags are "not reported", never "real". */
export function carbonText(carbon: EvaluationResult['carbon']): string {
  if (carbon === undefined || carbon.is_real === undefined) return 'not reported';
  if (carbon.is_real) return 'Measured series (reported as real by the backend)';
  return carbon.flat_curve === true ? 'Assumed: flat constant, not a real grid series' : 'Assumed: fallback values, not a real grid series';
}

// ------------------------------------------------------------------------------------------------ hard constraints

/** The envelope limits the harness can count, in display order. Unknown extra ids the backend counts are appended. */
export const KNOWN_HARD_CONSTRAINTS: ReadonlyArray<{ readonly id: string; readonly label: string }> = [
  { id: 'outlet_violation_steps', label: 'Outlet over limit' },
  { id: 'inlet_over_max_steps', label: 'Inlet over maximum' },
  { id: 'inlet_under_min_steps', label: 'Inlet under minimum' },
  { id: 'pue_over_max_steps', label: 'PUE over maximum' },
];

export type ConstraintState = 'violated' | 'none' | 'not_measured';
export type PolicyConstraintState = 'violated' | 'clean' | 'partial';

export interface ConstraintCell {
  readonly id: string;
  readonly state: ConstraintState;
  /** Mean violating steps per test episode, as sent; null when not measured. */
  readonly value: number | null;
  readonly text: string;
}

export interface ConstraintRow {
  readonly policyId: string;
  /** `clean` only when EVERY limit was measured and is zero; unmeasured limits give `partial`, never `clean`. */
  readonly state: PolicyConstraintState;
  readonly summary: string;
  readonly cells: readonly ConstraintCell[];
}

export interface HardConstraintView {
  readonly limits: ReadonlyArray<{ readonly id: string; readonly label: string }>;
  readonly rows: readonly ConstraintRow[];
  readonly violatingPolicies: number;
  readonly headline: string;
  /** The backend's own note, verbatim, when it sent one. */
  readonly backendNote: string | null;
  /** Set when the backend says no constant set-point satisfied the envelope on validation. */
  readonly comparatorCaveat: string | null;
}

export const COMPARATOR_CAVEAT =
  'No constant set-point satisfied every hard limit on the validation episodes, so the best_constant comparator is the highest-reward constant even though it violates the envelope.';

/**
 * Hard constraints are separate from the reward and never traded against it. A mean of 0 steps per episode means no
 * episode violated the limit; any value above 0 means at least one did. A limit that was not counted is "not
 * measured": it is NOT zero and it can never produce a clean status.
 */
export function hardConstraintView(r: EvaluationResult): HardConstraintView {
  const notMeasured = new Set(r.hard_constraints?.not_measured ?? []);
  const extra = (r.hard_constraints?.counted ?? []).filter((id) => !KNOWN_HARD_CONSTRAINTS.some((k) => k.id === id));
  const limits = [...KNOWN_HARD_CONSTRAINTS, ...extra.map((id) => ({ id, label: id }))];

  const rows: ConstraintRow[] = r.policies.map((p) => {
    const cells: ConstraintCell[] = limits.map(({ id }) => {
      const v = p.metrics[id];
      if (typeof v !== 'number' || notMeasured.has(id)) return { id, state: 'not_measured', value: null, text: 'not measured' };
      return v > 0 ? { id, state: 'violated', value: v, text: `${formatMetric(v)} steps/episode — violated` } : { id, state: 'none', value: v, text: '0 — none' };
    });
    const violated = cells.filter((c) => c.state === 'violated').length;
    const unmeasured = cells.filter((c) => c.state === 'not_measured').length;
    const state: PolicyConstraintState = violated > 0 ? 'violated' : unmeasured > 0 ? 'partial' : 'clean';
    const summary =
      state === 'violated'
        ? `Violates ${violated} of ${cells.length} limits`
        : state === 'partial'
          ? `No violation in the ${cells.length - unmeasured} measured limits; ${unmeasured} not measured`
          : 'No violation of any limit';
    return { policyId: p.policy_id, state, summary, cells };
  });

  const violatingPolicies = rows.filter((x) => x.state === 'violated').length;
  const anyUnmeasured = rows.some((x) => x.state === 'partial' || x.cells.some((c) => c.state === 'not_measured'));
  const headline =
    rows.length === 0
      ? 'No policies reported, so no hard-constraint result is available.'
      : violatingPolicies > 0
        ? `Hard-constraint violations: ${violatingPolicies} of ${rows.length} policies violate at least one limit on the test episodes.`
        : anyUnmeasured
          ? 'No violations in the limits that were measured; some limits were not measured in this report (that is not the same as zero).'
          : 'No policy violated any counted hard limit on the test episodes.';
  return {
    limits,
    rows,
    violatingPolicies,
    headline,
    backendNote: typeof r.hard_constraints?.note === 'string' && r.hard_constraints.note !== '' ? r.hard_constraints.note : null,
    comparatorCaveat: r.selection?.best_constant_envelope_feasible === false ? COMPARATOR_CAVEAT : null,
  };
}
