import { describe, expect, it } from 'vitest';
import { decidingConstraints, comparisonView, defaultComparison, policyOptions } from './comparison';
import { UNCERTAINTY_NOT_PROVIDED } from './model';
import { CAPTURED_BASELINES_ONLY as REAL, SYNTHETIC_B, clone, syntheticSchema2, syntheticWithPpo, withMetric } from './testFixtures';

const ppoWithEnvelope = (ok: boolean, extra: Record<string, number> = {}) =>
  syntheticWithPpo('B', {
    decision: {
      outcome: 'B',
      claim_allowed: 'none',
      reason: 'SYNTHETIC',
      detail: {
        per_baseline: {
          rule: { baseline_envelope_safe: false, seed_level_diff: { n: 5, mean: -1, ci_low: -2, ci_high: 0 } },
          best_constant: { baseline_envelope_safe: true },
        },
        envelope_selected_candidate: { ok, outlet_violation_steps: 0, inlet_over_max_steps: 0, inlet_under_min_steps: 0, ...extra },
      },
    },
  });

describe('defaultComparison / policyOptions', () => {
  it('reference = first non-PPO in backend order; compared = a PPO row when there is one; null below two policies', () => {
    expect(defaultComparison(REAL)).toEqual({ reference: 'rule', compared: 'best_constant' });
    expect(defaultComparison(SYNTHETIC_B)).toEqual({ reference: 'rule', compared: 'ppo_seed_0' });
    expect(defaultComparison({ ...REAL, policies: REAL.policies.slice(0, 1) })).toBeNull();
    expect(policyOptions(SYNTHETIC_B).map((o) => o.id)).toEqual(['rule', 'best_constant', 'ppo_seed_0']); // backend order, never sorted
  });
});

describe('comparisonView', () => {
  it('refuses fewer than two policies, the same policy twice, and an unknown id', () => {
    expect(comparisonView({ ...REAL, policies: [] }, 'rule', 'best_constant').valid).toBe(false);
    expect(comparisonView(REAL, 'rule', 'rule')).toMatchObject({ valid: false, problem: 'Choose two different policies.' });
    expect(comparisonView(REAL, 'rule', 'nope')).toMatchObject({ valid: false, problem: 'A selected policy is not in this report.' });
  });

  it('puts the four hard limits first in a fixed order; an unreported limit is "not provided", never zero', () => {
    const v = comparisonView(REAL, 'rule', 'best_constant');
    expect(v.hardRows.map((r) => r.id)).toEqual(['outlet_violation_steps', 'inlet_over_max_steps', 'inlet_under_min_steps', 'pue_over_max_steps']);
    const pue = v.hardRows.find((r) => r.id === 'pue_over_max_steps')!;
    expect(pue).toMatchObject({ reference: 'not provided', compared: 'not provided', difference: null, direction: null });
    expect(v.otherRows.map((r) => r.id)).not.toContain('inlet_under_min_steps');
  });

  it('difference is compared minus reference, with a direction word and the metric\'s own "better" as sent', () => {
    const r = clone(REAL);
    r.policies[0].metrics.energy_kwh = 1000;
    r.policies[1].metrics.energy_kwh = 900;
    const row = comparisonView(r, 'rule', 'best_constant').otherRows.find((x) => x.id === 'energy_kwh')!;
    expect(row).toMatchObject({ reference: '1,000', compared: '900', difference: '-100', direction: 'lower', percent: '-10.0%' });
    expect(row.better).toBe('lower');
    expect(row.definition).toMatch(/Facility energy/);
    const same = comparisonView(withMetric(r, 'best_constant', 'energy_kwh', 1000), 'rule', 'best_constant').otherRows.find((x) => x.id === 'energy_kwh')!;
    expect(same.direction).toBe('same');
  });

  it('no percent when the reference is 0, no difference when a value is missing', () => {
    const r = withMetric(syntheticSchema2(), 'rule', 'energy_kwh', 0);
    const row = comparisonView(r, 'rule', 'best_constant').otherRows.find((x) => x.id === 'energy_kwh')!;
    expect(row.percent).toBeNull();
    const m = withMetric(syntheticSchema2(), 'best_constant', 'energy_kwh', undefined);
    const miss = comparisonView(m, 'rule', 'best_constant').otherRows.find((x) => x.id === 'energy_kwh')!;
    expect(miss).toMatchObject({ compared: 'not provided', difference: null, direction: null });
  });

  it('metric rows keep first-appearance order (nothing is sorted by value)', () => {
    const ids = comparisonView(REAL, 'rule', 'best_constant').otherRows.map((r) => r.id);
    expect(ids).toEqual(Object.keys(REAL.policies[0].metrics).filter((id) => !id.includes('violation') && !id.startsWith('inlet_')));
  });

  it('eligibility comes from the hard constraints alone', () => {
    expect(comparisonView(REAL, 'rule', 'best_constant').eligibility).toMatch(/^Both policies violate at least one hard limit/);
    const clean = syntheticSchema2();
    expect(comparisonView(clean, 'rule', 'best_constant').eligibility).toBe('Neither policy violated any counted hard limit.');
    const cmpBad = withMetric(clean, 'best_constant', 'pue_over_max_steps', 2);
    expect(comparisonView(cmpBad, 'rule', 'best_constant').eligibility).toMatch(/^The compared policy violates at least one hard limit.*A better reward never offsets/);
    expect(comparisonView(cmpBad, 'best_constant', 'rule').eligibility).toMatch(/^The reference policy violates/);
    const partial = withMetric(clean, 'rule', 'pue_over_max_steps', undefined);
    expect(comparisonView(partial, 'rule', 'best_constant').eligibility).toMatch(/not the same as zero/);
  });

  it('intervals only for the PPO candidate vs a baseline the report itself covers; otherwise "not provided"', () => {
    const ppoRule = comparisonView(SYNTHETIC_B, 'rule', 'ppo_seed_0');
    expect(ppoRule.uncertainty?.map((u) => u.scope)).toEqual(['training seeds', 'test scenarios']);
    expect(ppoRule.uncertaintyNote).toMatch(/none are computed here/);
    const baselines = comparisonView(SYNTHETIC_B, 'rule', 'best_constant');
    expect(baselines.uncertainty).toBeNull();
    expect(baselines.uncertaintyNote).toContain(UNCERTAINTY_NOT_PROVIDED);
    const reversed = comparisonView(SYNTHETIC_B, 'ppo_seed_0', 'rule'); // reference is the PPO row: not the covered direction
    expect(reversed.uncertainty).toBeNull();
  });

  it('states the scenario set from the report, or that it is not reported', () => {
    expect(comparisonView(REAL, 'rule', 'best_constant').sameScenarios).toBe("Both policies were scored on the report's 60 test scenarios (set b8329f196c910981); the values are means over them.");
    const r = clone(REAL);
    delete r.scenario_sets;
    expect(comparisonView(r, 'rule', 'best_constant').sameScenarios).toMatch(/not reported/);
  });
});

describe('decidingConstraints (read, never computed)', () => {
  it('real baselines-only report has no PPO decision detail', () => {
    expect(decidingConstraints(REAL.decision)).toEqual({ candidateWithinEnvelope: null, candidateViolations: [], unsafeBaselines: [] });
  });

  it('reads the selected candidate\'s violated limits and the unsafe baselines', () => {
    const d = decidingConstraints(ppoWithEnvelope(false, { inlet_under_min_steps: 3, pue_over_max_steps: 1.5 }).decision);
    expect(d.candidateWithinEnvelope).toBe(false);
    expect(d.candidateViolations).toEqual([
      { id: 'inlet_under_min_steps', steps: 3 },
      { id: 'pue_over_max_steps', steps: 1.5 },
    ]);
    expect(d.unsafeBaselines).toEqual(['rule']);
    expect(decidingConstraints(ppoWithEnvelope(true).decision).candidateWithinEnvelope).toBe(true);
  });

  it('malformed detail degrades to "nothing reported"', () => {
    for (const detail of [undefined, null, 5, [], { envelope_selected_candidate: 'x', per_baseline: 3 }]) {
      expect(decidingConstraints({ outcome: 'B', claim_allowed: 'none', detail })).toEqual({ candidateWithinEnvelope: null, candidateViolations: [], unsafeBaselines: [] });
    }
  });
});
