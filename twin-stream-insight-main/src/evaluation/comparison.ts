/**
 * Task 16: head-to-head comparison of two policies inside ONE evaluation report.
 *
 * Both policies come from the same report, so they were scored on the same test scenario set (shown with its id);
 * nothing here crosses reports (a different report may run other physics, scenarios or carbon: not comparable).
 * Everything is READ from the payload. Nothing is re-scored, no interval is computed, and no overall winner is
 * declared: hard constraints are shown first and decide eligibility; the report's own decision rule is the only verdict.
 */
import type { EvaluationDecision, EvaluationPolicy, EvaluationResult, MetricDefinition } from './schema';
import {
  KNOWN_HARD_CONSTRAINTS,
  NOT_PROVIDED,
  UNCERTAINTY_NOT_PROVIDED,
  formatMetric,
  hardConstraintView,
  pairedDifferences,
  type ConstraintRow,
  type PairedDifferenceView,
} from './model';

export const COMPARISON_MIN_POLICIES = 2;

export interface PolicyOption {
  readonly id: string;
  readonly kind: string | null;
}

export function policyOptions(r: EvaluationResult): PolicyOption[] {
  return r.policies.map((p) => ({ id: p.policy_id, kind: p.kind ?? null }));
}

/** Defaults carry no ranking: the reference is the first non-PPO policy in the backend's order, the compared one a PPO row if any. */
export function defaultComparison(r: EvaluationResult): { reference: string; compared: string } | null {
  const opts = policyOptions(r);
  if (opts.length < COMPARISON_MIN_POLICIES) return null;
  const isPpo = (o: PolicyOption) => o.kind === 'ppo';
  const reference = opts.find((o) => !isPpo(o)) ?? opts[0];
  const compared = opts.find((o) => isPpo(o) && o.id !== reference.id) ?? opts.find((o) => o.id !== reference.id) ?? opts[1];
  return { reference: reference.id, compared: compared.id };
}

export type Direction = 'lower' | 'higher' | 'same';

export interface ComparisonMetricRow {
  readonly id: string;
  readonly reference: string;
  readonly compared: string;
  /** Compared minus reference, only when both values were provided. */
  readonly difference: string | null;
  readonly percent: string | null;
  readonly direction: Direction | null;
  /** The backend's own `better` for the metric, as sent ("lower"/"higher"/…); null when not provided. */
  readonly better: string | null;
  readonly definition: string | null;
}

export interface DecidingConstraints {
  /** `ok` of `decision.detail.envelope_selected_candidate`; null when the report carries no PPO decision detail. */
  readonly candidateWithinEnvelope: boolean | null;
  /** Hard-limit metric ids with at least one violating step for the selected candidate. */
  readonly candidateViolations: ReadonlyArray<{ readonly id: string; readonly steps: number }>;
  /** Baselines the report judged not envelope-safe (so they cannot be offered as a replacement). */
  readonly unsafeBaselines: readonly string[];
}

export interface ComparisonView {
  readonly valid: boolean;
  /** Why no comparison is shown, when `valid` is false. */
  readonly problem: string | null;
  readonly referenceId: string;
  readonly comparedId: string;
  readonly constraints: readonly ConstraintRow[]; // [reference, compared]
  /** Plain-language eligibility statement from the hard constraints alone (not a performance verdict). */
  readonly eligibility: string;
  readonly hardRows: readonly ComparisonMetricRow[];
  readonly otherRows: readonly ComparisonMetricRow[];
  readonly uncertainty: ReadonlyArray<PairedDifferenceView> | null;
  readonly uncertaintyNote: string;
  readonly sameScenarios: string;
  readonly deciding: DecidingConstraints;
}

const HARD_IDS = new Set(KNOWN_HARD_CONSTRAINTS.map((k) => k.id));

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** What the report says decided eligibility, read defensively from `decision.detail`. Never computed here. */
export function decidingConstraints(decision: EvaluationDecision): DecidingConstraints {
  const detail = decision.detail;
  const env = isRecord(detail) ? detail.envelope_selected_candidate : undefined;
  const per = isRecord(detail) ? detail.per_baseline : undefined;
  const violations: Array<{ id: string; steps: number }> = [];
  let ok: boolean | null = null;
  if (isRecord(env)) {
    ok = typeof env.ok === 'boolean' ? env.ok : null;
    for (const [id, v] of Object.entries(env)) if (HARD_IDS.has(id) && typeof v === 'number' && v > 0) violations.push({ id, steps: v });
  }
  const unsafe: string[] = [];
  if (isRecord(per)) for (const [name, entry] of Object.entries(per)) if (isRecord(entry) && entry.baseline_envelope_safe === false) unsafe.push(name);
  return { candidateWithinEnvelope: ok, candidateViolations: violations, unsafeBaselines: unsafe };
}

function direction(d: number): Direction {
  return d < 0 ? 'lower' : d > 0 ? 'higher' : 'same';
}

function metricRow(id: string, a: EvaluationPolicy, b: EvaluationPolicy, defs: Readonly<Record<string, MetricDefinition>> | undefined): ComparisonMetricRow {
  const av = a.metrics[id];
  const bv = b.metrics[id];
  const both = typeof av === 'number' && typeof bv === 'number';
  const d = both ? bv - av : null;
  return {
    id,
    reference: typeof av === 'number' ? formatMetric(av) : NOT_PROVIDED,
    compared: typeof bv === 'number' ? formatMetric(bv) : NOT_PROVIDED,
    difference: d === null ? null : formatMetric(d),
    percent: d !== null && both && av !== 0 ? `${((d / Math.abs(av)) * 100).toFixed(1)}%` : null,
    direction: d === null ? null : direction(d),
    better: defs?.[id]?.better ?? null,
    definition: defs?.[id]?.definition ?? null,
  };
}

export function comparisonView(r: EvaluationResult, referenceId: string, comparedId: string): ComparisonView {
  const empty = (problem: string): ComparisonView => ({
    valid: false,
    problem,
    referenceId,
    comparedId,
    constraints: [],
    eligibility: '',
    hardRows: [],
    otherRows: [],
    uncertainty: null,
    uncertaintyNote: '',
    sameScenarios: '',
    deciding: decidingConstraints(r.decision),
  });
  if (r.policies.length < COMPARISON_MIN_POLICIES) return empty('This report has fewer than two policies, so there is nothing to compare.');
  const a = r.policies.find((p) => p.policy_id === referenceId);
  const b = r.policies.find((p) => p.policy_id === comparedId);
  if (a === undefined || b === undefined) return empty('A selected policy is not in this report.');
  if (a.policy_id === b.policy_id) return empty('Choose two different policies.');

  const hc = hardConstraintView(r);
  const rows = [hc.rows.find((x) => x.policyId === a.policy_id), hc.rows.find((x) => x.policyId === b.policy_id)].filter((x): x is ConstraintRow => x !== undefined);

  const ids: string[] = [];
  for (const p of [a, b]) for (const id of Object.keys(p.metrics)) if (!ids.includes(id)) ids.push(id);
  const hardIds = hc.limits.map((l) => l.id); // fixed display order, including limits one side did not report
  const other = ids.filter((id) => !hardIds.includes(id));
  const toRow = (id: string) => metricRow(id, a, b, r.metrics);

  const [ra, rb] = rows;
  const eligibility =
    ra === undefined || rb === undefined
      ? 'Hard-constraint status is not available for one of the policies.'
      : ra.state === 'violated' && rb.state === 'violated'
        ? 'Both policies violate at least one hard limit. Neither is eligible as a safe operating strategy, whatever its reward.'
        : rb.state === 'violated'
          ? `The compared policy violates at least one hard limit (${rb.summary}); the reference does not. A better reward never offsets a violated limit.`
          : ra.state === 'violated'
            ? `The reference policy violates at least one hard limit (${ra.summary}); the compared policy does not.`
            : ra.state === 'partial' || rb.state === 'partial'
              ? 'No violation in the limits that were measured; some limits were not measured for at least one policy (that is not the same as zero).'
              : 'Neither policy violated any counted hard limit.';

  // The report carries paired intervals ONLY for the PPO candidate vs each baseline; anything else has none.
  const paired = pairedDifferences(r.decision);
  const isPair = b.kind === 'ppo' && paired.some((p) => p.baseline === a.policy_id);
  const uncertainty = isPair ? paired.filter((p) => p.baseline === a.policy_id) : null;
  const test = r.scenario_sets?.test;
  return {
    valid: true,
    problem: null,
    referenceId: a.policy_id,
    comparedId: b.policy_id,
    constraints: rows,
    eligibility,
    hardRows: hardIds.map(toRow),
    otherRows: other.map(toRow),
    uncertainty,
    uncertaintyNote: isPair
      ? 'Paired differences (compared minus reference) exactly as the report sent them; none are computed here.'
      : `${UNCERTAINTY_NOT_PROVIDED}: this report carries paired intervals only for the PPO candidate against each baseline, so the differences above are differences of means with no interval.`,
    sameScenarios:
      test === undefined
        ? 'The test scenario set is not reported. Both policies come from the same report.'
        : `Both policies were scored on the report's ${test.n} test scenarios (set ${test.id}); the values are means over them.`,
    deciding: decidingConstraints(r.decision),
  };
}
