/**
 * FE-17 test fixtures.
 *
 * REAL: `fixtures/baselines-only.detail.json` and `fixtures/list.json` are the committed captures of the real backend
 * (docs/frontend/contracts/G-EVAL.capture-*.json, BE-G2). They are the primary acceptance data.
 *
 * SYNTHETIC SHAPE FIXTURES: outcomes A, B and C have never been produced on this repo (no PPO candidate was ever
 * evaluated). The fixtures below are built from the documented shape of `decide_outcome()` and are NOT results.
 * Every one is named `SYNTHETIC_*`, carries a synthetic evaluation id, and uses obviously artificial numbers.
 */
import type { EvaluationList, EvaluationResult } from './schema';

// Same loading pattern as src/scenarios/testFixtures.ts (no `resolveJsonModule` dependency).
const modules = import.meta.glob('./fixtures/*.json', { eager: true, import: 'default' }) as Record<string, unknown>;
const baselinesOnly = modules['./fixtures/baselines-only.detail.json'];
const list = modules['./fixtures/list.json'] as EvaluationList;

export const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;

export const CAPTURED_BASELINES_ONLY = baselinesOnly as unknown as EvaluationResult;
export const CAPTURED_LIST = list;

const diff = (mean: number, lo: number, hi: number) => ({ n: 5, mean, sd: 1, se: 0.5, df: 4, t_critical: 2.776, ci_low: lo, ci_high: hi });

/** Baselines plus one PPO row, with paired differences, and the given outcome code. Synthetic shape only. */
export function syntheticWithPpo(outcome: string, over: Partial<EvaluationResult> = {}): EvaluationResult {
  const base = clone(CAPTURED_BASELINES_ONLY);
  const metricIds = Object.keys(base.policies[0].metrics);
  const ppoMetrics = Object.fromEntries(metricIds.map((id, i) => [id, 100 + i]));
  return {
    ...base,
    evaluation_id: `synthetic_${outcome}`,
    policies: [
      ...base.policies,
      // Deliberately NOT the lowest/highest anywhere: row order must stay the backend's regardless of values.
      { policy_id: 'ppo_seed_0', kind: 'ppo', metrics: ppoMetrics },
    ],
    decision: {
      outcome,
      claim_allowed: outcome === 'A' ? 'simulator-validated candidate' : 'none',
      reason: `SYNTHETIC reason text for outcome ${outcome}`,
      detail: {
        per_baseline: {
          rule: { seed_level_diff: diff(-1.5, -2.5, -0.5), scenario_level_diff: diff(0.25, -0.75, 1.25) },
          best_constant: { seed_level_diff: { n: 5, mean: 0.1 }, scenario_level_diff: diff(0, -1, 1) },
        },
      },
    },
    ...over,
  } as EvaluationResult;
}

export const SYNTHETIC_A = syntheticWithPpo('A');
export const SYNTHETIC_B = syntheticWithPpo('B');
export const SYNTHETIC_C = syntheticWithPpo('C');
export const SYNTHETIC_UNKNOWN = syntheticWithPpo('INCONCLUSIVE');
