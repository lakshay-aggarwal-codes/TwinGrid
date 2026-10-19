/* eslint-disable @typescript-eslint/no-explicit-any -- mutation helpers edit parsed JSON of unknown shape */
import { describe, expect, it } from 'vitest';
import { isFailure, isSuccess, parseApi } from '@/contract';
import { EvaluationListSchema, EvaluationResultSchema } from './schema';
import { CAPTURED_BASELINES_ONLY, CAPTURED_LIST, SYNTHETIC_A, clone } from './testFixtures';

describe('evaluation contract (real captures)', () => {
  it('parses the captured baselines-only detail unchanged', () => {
    const r = parseApi(EvaluationResultSchema, clone(CAPTURED_BASELINES_ONLY), 'test');
    expect(isSuccess(r)).toBe(true);
    if (isSuccess(r)) {
      expect(r.data.decision.outcome).toBe('NOT_EVALUATED');
      expect(r.data.decision.claim_allowed).toBe('none');
      expect(r.data.policies.map((p) => p.policy_id)).toEqual(['rule', 'best_constant']);
    }
  });

  it('parses the captured list', () => {
    expect(isSuccess(parseApi(EvaluationListSchema, clone(CAPTURED_LIST), 'test'))).toBe(true);
  });

  it('parses a synthetic PPO-shaped result (shape only)', () => {
    expect(isSuccess(parseApi(EvaluationResultSchema, clone(SYNTHETIC_A), 'test'))).toBe(true);
  });
});

describe('evaluation contract (mutations fail with the path)', () => {
  const mutate = (fn: (r: Record<string, any>) => void) => {
    const r = clone(CAPTURED_BASELINES_ONLY) as unknown as Record<string, any>;
    fn(r);
    return parseApi(EvaluationResultSchema, r, 'test');
  };

  it.each([
    ['decision.outcome missing', (r: Record<string, any>) => delete r.decision.outcome, 'decision.outcome'],
    ['decision.claim_allowed missing', (r: Record<string, any>) => delete r.decision.claim_allowed, 'decision.claim_allowed'],
    ['schema_version is neither 1 nor 2', (r: Record<string, any>) => (r.schema_version = 3), 'schema_version'],
    ['policies is not an array', (r: Record<string, any>) => (r.policies = {}), 'policies'],
    ['a metric is a string', (r: Record<string, any>) => (r.policies[0].metrics.mean_pue = '1.2'), 'policies[0].metrics.mean_pue'],
    ['a metric is not finite', (r: Record<string, any>) => (r.policies[0].metrics.mean_pue = null), 'policies[0].metrics.mean_pue'],
    ['evaluation_id missing', (r: Record<string, any>) => delete r.evaluation_id, 'evaluation_id'],
  ])('%s', (_name, fn, path) => {
    const r = mutate(fn);
    expect(isFailure(r)).toBe(true);
    if (isFailure(r)) expect(r.error.issues.map((i) => i.path)).toContain(path);
  });

  it('accepts schema_version 2 (A2) and reads the executed physics, hard_constraints and selection', () => {
    const r = mutate((x) => {
      x.schema_version = 2;
      x.physics_version_executed = '1';
      x.hard_constraints = { counted: ['pue_over_max_steps'], not_measured: [], note: null };
      x.selection = { best_constant_envelope_feasible: false, extra: 1 };
    });
    expect(isSuccess(r)).toBe(true);
    if (isSuccess(r)) {
      expect(r.data.schema_version).toBe(2);
      expect(r.data.physics_version_executed).toBe('1');
      expect(r.data.hard_constraints?.counted).toEqual(['pue_over_max_steps']);
      expect(r.data.selection?.best_constant_envelope_feasible).toBe(false);
    }
  });

  it('a malformed hard_constraints block is a contract violation, not silently ignored', () => {
    const r = mutate((x) => (x.hard_constraints = { counted: 'pue', not_measured: [] }));
    expect(isFailure(r)).toBe(true);
  });

  it('does not invent values: ci_level and outcome_definitions stay absent when the backend omits them', () => {
    const r = mutate((x) => {
      delete x.ci_level;
      delete x.outcome_definitions;
    });
    expect(isSuccess(r)).toBe(true);
    if (isSuccess(r)) {
      expect(r.data.ci_level).toBeUndefined();
      expect(r.data.outcome_definitions).toBeUndefined();
    }
  });
});
