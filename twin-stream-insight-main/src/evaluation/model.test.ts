import { describe, expect, it } from 'vitest';
import {
  DEFINITION_NOT_PROVIDED,
  NOT_PROVIDED,
  UNCERTAINTY_NOT_PROVIDED,
  ciLevelText,
  formatMetric,
  identityRows,
  outcomeView,
  pairedDifferences,
  tableView,
} from './model';
import { CAPTURED_BASELINES_ONLY as REAL, SYNTHETIC_A, SYNTHETIC_B, SYNTHETIC_C, SYNTHETIC_UNKNOWN, clone } from './testFixtures';

const view = (r: typeof REAL) => outcomeView(r.decision, r.outcome_definitions);

describe('outcomeView', () => {
  it('real data: Not evaluated — claim allowed: none, with the backend reason and no invented definition', () => {
    const o = view(REAL);
    expect(o.kind).toBe('NOT_EVALUATED');
    expect(o.headline).toBe('Not evaluated — claim allowed: none');
    expect(o.claimAllowed).toBe('none');
    expect(o.reason).toBe(REAL.decision.reason);
    expect(o.definition).toBe(DEFINITION_NOT_PROVIDED);
    expect(o.definitionProvided).toBe(false);
  });

  it.each([
    ['A', SYNTHETIC_A],
    ['B', SYNTHETIC_B],
    ['C', SYNTHETIC_C],
  ])('outcome %s shows the backend definition text verbatim', (code, r) => {
    const o = view(r);
    expect(o.kind).toBe(code);
    expect(o.definition).toBe(REAL.outcome_definitions?.[code]);
    expect(o.definitionProvided).toBe(true);
    expect(o.claimAllowed).toBe(r.decision.claim_allowed);
  });

  it('a code without a backend definition shows the code and "definition not provided"', () => {
    const r = clone(SYNTHETIC_B);
    delete r.outcome_definitions;
    const o = view(r);
    expect(o.kind).toBe('B');
    expect(o.definition).toBe(DEFINITION_NOT_PROVIDED);
  });

  it('an unknown outcome string stays unknown and is shown as-is', () => {
    const o = view(SYNTHETIC_UNKNOWN);
    expect(o.kind).toBe('unrecognised');
    expect(o.headline).toBe('Unrecognised outcome: INCONCLUSIVE');
    expect(o.definition).toBe(DEFINITION_NOT_PROVIDED);
  });

  it('a lower-case code is not coerced', () => {
    const r = clone(SYNTHETIC_A);
    r.decision.outcome = 'a';
    expect(view(r).kind).toBe('unrecognised');
  });
});

describe('tableView', () => {
  it('real data: rows are the backend policies in order, no PPO row, only reported metrics as columns', () => {
    const t = tableView(REAL.policies, REAL.metrics, REAL.carbon);
    expect(t.rows.map((r) => r.policyId)).toEqual(['rule', 'best_constant']);
    expect(t.columns.map((c) => c.id)).toEqual(Object.keys(REAL.policies[0].metrics));
  });

  it('never reorders rows, whatever the values are', () => {
    const r = clone(SYNTHETIC_A);
    // make the PPO row the numerically smallest everywhere, and put it first
    r.policies = [r.policies[2], r.policies[1], r.policies[0]].map((p, i) => ({ ...p, metrics: Object.fromEntries(Object.keys(p.metrics).map((k) => [k, i === 0 ? -1 : 1000 - i])) }));
    const order = r.policies.map((p) => p.policy_id);
    expect(tableView(r.policies, r.metrics, r.carbon).rows.map((x) => x.policyId)).toEqual(order);
  });

  it('shows "not provided" for a metric a policy lacks, never 0 or blank', () => {
    const r = clone(REAL);
    delete r.policies[1].metrics.mean_pue;
    const t = tableView(r.policies, r.metrics, r.carbon);
    const col = t.columns.findIndex((c) => c.id === 'mean_pue');
    expect(t.rows[1].cells[col].text).toBe(NOT_PROVIDED);
    expect(t.rows[1].cells[col].exact).toBeNull();
  });

  it('column hints come from the backend `better` field only', () => {
    const t = tableView(REAL.policies, REAL.metrics, REAL.carbon);
    expect(t.columns.find((c) => c.id === 'mean_pue')?.hint).toBe('lower is better');
    expect(t.columns.find((c) => c.id === 'total_reward')?.hint).toBe('higher is better');
    expect(tableView(REAL.policies, undefined, REAL.carbon).columns.every((c) => c.hint === null)).toBe(true);
  });

  it('carbon columns carry a caveat when the backend says carbon is not real', () => {
    const t = tableView(REAL.policies, REAL.metrics, REAL.carbon);
    expect(t.columns.find((c) => c.id === 'carbon_gco2')?.caveat).toBe('Fallback carbon (flat constant)');
    expect(t.columns.find((c) => c.id === 'energy_kwh')?.caveat).toBeNull();
    expect(tableView(REAL.policies, REAL.metrics, undefined).columns.find((c) => c.id === 'carbon_gco2')?.caveat).toBe('carbon data source not reported');
    expect(tableView(REAL.policies, REAL.metrics, { is_real: true }).columns.find((c) => c.id === 'carbon_gco2')?.caveat).toBeNull();
  });

  it('keeps the exact value for the tooltip and rounds only the display', () => {
    const t = tableView(REAL.policies, REAL.metrics, REAL.carbon);
    const cell = t.rows[0].cells[t.columns.findIndex((c) => c.id === 'mean_pue')];
    expect(cell.exact).toBe(String(REAL.policies[0].metrics.mean_pue));
    expect(cell.text).toBe(formatMetric(REAL.policies[0].metrics.mean_pue));
  });
});

describe('pairedDifferences', () => {
  it('real baselines-only data has no CIs to show', () => {
    expect(pairedDifferences(REAL.decision)).toEqual([]);
  });

  it('reads the backend intervals as sent', () => {
    const d = pairedDifferences(SYNTHETIC_A.decision);
    expect(d.map((x) => `${x.baseline}:${x.scope}`)).toEqual(['rule:training seeds', 'rule:test scenarios', 'best_constant:training seeds', 'best_constant:test scenarios']);
    expect(d[0].text).toBe(`${formatMetric(-1.5)} [${formatMetric(-2.5)}, ${formatMetric(-0.5)}]`);
    expect(d[0].provided).toBe(true);
    // an interval that includes zero is displayed, not hidden
    expect(d[1].text).toBe(`${formatMetric(0.25)} [${formatMetric(-0.75)}, ${formatMetric(1.25)}]`);
  });

  it('a missing bound is "uncertainty not provided" and nothing is imputed', () => {
    const d = pairedDifferences(SYNTHETIC_A.decision).find((x) => x.baseline === 'best_constant' && x.scope === 'training seeds');
    expect(d?.text).toBe(UNCERTAINTY_NOT_PROVIDED);
    expect(d?.provided).toBe(false);
  });

  it('tolerates a malformed detail', () => {
    for (const detail of [null, 5, 'x', [], { per_baseline: 3 }, { per_baseline: { rule: 'x' } }]) {
      expect(pairedDifferences({ ...SYNTHETIC_A.decision, detail })).toEqual([]);
    }
  });

  it('ci level wording', () => {
    expect(ciLevelText(0.95)).toBe('level 0.95');
    expect(ciLevelText(undefined)).toBe('level not provided');
  });
});

describe('identityRows', () => {
  it('real data: evaluation scenario set, prereg hash, physics version; dataset identity is "not provided"', () => {
    const rows = Object.fromEntries(identityRows(REAL).map((r) => [r.id, r]));
    expect(rows['evaluation-scenario-set'].value).toBe(REAL.scenario_set_id);
    expect(rows.prereg.value).toBe(REAL.preregistration_sha256);
    expect(rows.physics.value).toBe(REAL.physics_version);
    expect(rows.dataset).toMatchObject({ value: NOT_PROVIDED, reported: false });
    expect(rows['validation-set'].value).toBe('a290e92dcf0037b0 (n=30)');
    expect(rows['test-set'].value).toBe('b8329f196c910981 (n=60)');
  });

  it('missing fields are "not provided", never blank', () => {
    const r = clone(REAL);
    delete r.scenario_set_id;
    delete r.preregistration_sha256;
    const rows = Object.fromEntries(identityRows(r).map((x) => [x.id, x]));
    expect(rows['evaluation-scenario-set'].value).toBe(NOT_PROVIDED);
    expect(rows.prereg.value).toBe(NOT_PROVIDED);
  });
});
