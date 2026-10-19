import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  CAPTURED_BASELINES_ONLY,
  SYNTHETIC_A,
  SYNTHETIC_B,
  SYNTHETIC_C,
  SYNTHETIC_UNKNOWN,
  clone,
  syntheticSchema2,
  syntheticWithPpo,
  withMetric,
} from '@/evaluation/testFixtures';

vi.mock('@/lib/errorReporter.ts', () => ({ reportError: vi.fn() }));

import { EvaluationView } from './EvaluationView';

afterEach(cleanup);

const rowIds = () => [...document.querySelectorAll('[data-policy-row]')].map((r) => r.getAttribute('data-policy-row'));

describe('EvaluationView: real baselines-only report (primary acceptance fixture)', () => {
  it('shows "Not evaluated — claim allowed: none" prominently and no PPO row', () => {
    render(<EvaluationView result={clone(CAPTURED_BASELINES_ONLY)} />);
    expect(screen.getByTestId('outcome-headline')).toHaveTextContent('Not evaluated — claim allowed: none');
    expect(screen.getByTestId('outcome-claim')).toHaveTextContent('Claim allowed: none');
    expect(screen.getByTestId('outcome-reason')).toHaveTextContent(CAPTURED_BASELINES_ONLY.decision.reason as string);
    expect(screen.getByTestId('outcome-definition')).toHaveTextContent('NOT_EVALUATED — definition not provided');
    expect(rowIds()).toEqual(['rule', 'best_constant']);
    expect(document.querySelector('[data-policy-row*="ppo" i]')).toBeNull();
  });

  it('carries the simulator-only provenance and the evaluation identity strip', () => {
    render(<EvaluationView result={clone(CAPTURED_BASELINES_ONLY)} />);
    const badge = document.querySelector('[data-provenance-badge]');
    expect(badge).toHaveAttribute('data-provenance-badge', 'simulated');
    expect(within(badge as HTMLElement).getByText('Simulator-only')).toBeInTheDocument();
    const identity = screen.getByTestId('evaluation-identity');
    expect(within(identity).getByText('0fcafef9d28fd539')).toBeInTheDocument();
    expect(within(identity).getByText(CAPTURED_BASELINES_ONLY.preregistration_sha256 as string)).toBeInTheDocument();
    expect(within(identity).getByText('Evaluation scenario set')).toBeInTheDocument();
    expect(within(identity).getByText('Dataset identity').closest('[data-identity]')).toHaveAttribute('data-reported', 'false');
  });

  it('shows the unreachable-constraint facts as given and labels fallback carbon', () => {
    render(<EvaluationView result={clone(CAPTURED_BASELINES_ONLY)} />);
    const rule = document.querySelector('[data-policy-row="rule"]') as HTMLElement;
    expect(rule.querySelector('[data-cell="inlet_under_min_steps"]')).toHaveTextContent('288');
    // the label appears on the provenance strip AND under the carbon columns (two places on purpose)
    expect(document.querySelector('[data-provenance-strip] [data-flag="fallback"], [data-provenance-badge] [data-flag="fallback"]')).not.toBeNull();
    expect(screen.getAllByText('Fallback carbon (flat constant)').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByTestId('table-uncertainty')).toHaveTextContent('uncertainty not provided');
    expect(screen.getByTestId('no-paired-differences')).toBeInTheDocument();
  });

  it('marks no row as best: no highlight attribute or class on any row', () => {
    render(<EvaluationView result={clone(CAPTURED_BASELINES_ONLY)} />);
    for (const tr of document.querySelectorAll('[data-policy-row]')) {
      expect(tr.getAttributeNames().filter((n) => /best|winner|highlight|selected/i.test(n))).toEqual([]);
      expect(tr.className).not.toMatch(/success|green|primary|highlight|bg-/);
    }
  });
});

describe('EvaluationView: outcome fixtures (A/B/C are SYNTHETIC shape fixtures, not results)', () => {
  it.each([
    ['A', SYNTHETIC_A],
    ['B', SYNTHETIC_B],
    ['C', SYNTHETIC_C],
  ])('outcome %s: backend definition and claim shown verbatim; PPO is one plain row after the baselines', (code, result) => {
    render(<EvaluationView result={clone(result)} />);
    const banner = screen.getByLabelText('Evaluation outcome');
    expect(banner).toHaveAttribute('data-outcome', code);
    expect(screen.getByTestId('outcome-headline')).toHaveTextContent(`Outcome class ${code}`);
    expect(screen.getByTestId('outcome-definition')).toHaveTextContent(CAPTURED_BASELINES_ONLY.outcome_definitions?.[code] as string);
    expect(screen.getByTestId('outcome-claim')).toHaveTextContent(result.decision.claim_allowed);
    expect(rowIds()).toEqual(['rule', 'best_constant', 'ppo_seed_0']);
    const ppo = document.querySelector('[data-policy-row="ppo_seed_0"]') as HTMLElement;
    const rule = document.querySelector('[data-policy-row="rule"]') as HTMLElement;
    expect(ppo.className).toBe(rule.className);
    expect(ppo.getAttributeNames().sort()).toEqual(rule.getAttributeNames().sort());
  });

  it('every outcome banner has identical weight (same classes), so a negative result is never toned down', () => {
    const classes = [CAPTURED_BASELINES_ONLY, SYNTHETIC_A, SYNTHETIC_B, SYNTHETIC_C, SYNTHETIC_UNKNOWN].map((r) => {
      const { unmount } = render(<EvaluationView result={clone(r)} />);
      const cls = screen.getByLabelText('Evaluation outcome').className;
      unmount();
      return cls;
    });
    expect(new Set(classes).size).toBe(1);
  });

  it('each outcome kind has its own icon shape (not colour alone)', () => {
    const icons = [CAPTURED_BASELINES_ONLY, SYNTHETIC_A, SYNTHETIC_B, SYNTHETIC_C, SYNTHETIC_UNKNOWN].map((r) => {
      const { unmount } = render(<EvaluationView result={clone(r)} />);
      const icon = document.querySelector('[data-outcome-icon]');
      expect(icon).toHaveAttribute('aria-hidden', 'true');
      const kind = icon?.getAttribute('data-outcome-icon');
      unmount();
      return kind;
    });
    expect(new Set(icons).size).toBe(5);
  });

  it('shows the paired-difference intervals as sent, including one that includes zero, and "uncertainty not provided" for a gap', () => {
    render(<EvaluationView result={clone(SYNTHETIC_A)} />);
    const section = screen.getByLabelText('Paired differences');
    expect(section).toHaveTextContent('Paired difference (PPO minus baseline), t-based, level 0.95');
    expect(section.querySelector('[data-paired="rule:test scenarios"]')).toHaveTextContent('0.25 [-0.75, 1.25]');
    expect(section.querySelector('[data-paired="best_constant:training seeds"]')).toHaveTextContent('uncertainty not provided');
  });

  it('says "level not provided" when the backend sends no ci_level', () => {
    const r = clone(SYNTHETIC_A);
    delete r.ci_level;
    render(<EvaluationView result={r} />);
    expect(screen.getByLabelText('Paired differences')).toHaveTextContent('level not provided');
  });

  it('unknown outcome (e.g. "INCONCLUSIVE") renders neutrally as an unrecognised code', () => {
    render(<EvaluationView result={clone(SYNTHETIC_UNKNOWN)} />);
    expect(screen.getByLabelText('Evaluation outcome')).toHaveAttribute('data-outcome', 'unrecognised');
    expect(screen.getByTestId('outcome-headline')).toHaveTextContent('Unrecognised outcome: INCONCLUSIVE');
  });

  it('does not sort rows by any metric: a PPO row with the lowest values still comes last', () => {
    const r = syntheticWithPpo('A');
    for (const k of Object.keys(r.policies[2].metrics)) r.policies[2].metrics[k] = -1e6;
    render(<EvaluationView result={r} />);
    expect(rowIds()).toEqual(['rule', 'best_constant', 'ppo_seed_0']);
  });

  it('a policy kind or id the client does not know is shown as sent', () => {
    const r = clone(CAPTURED_BASELINES_ONLY);
    r.policies.push({ policy_id: 'mpc_x', kind: 'mpc', metrics: { mean_pue: 1.5 } });
    render(<EvaluationView result={r} />);
    expect(rowIds()).toEqual(['rule', 'best_constant', 'mpc_x']);
    const mpc = document.querySelector('[data-policy-row="mpc_x"]') as HTMLElement;
    expect(mpc.querySelector('[data-cell="inlet_under_min_steps"]')).toHaveTextContent('not provided');
  });

  it('a report with no policies says so instead of rendering an empty table', () => {
    const r = clone(CAPTURED_BASELINES_ONLY);
    r.policies = [];
    render(<EvaluationView result={r} />);
    expect(screen.getByTestId('no-policies')).toBeInTheDocument();
    expect(screen.queryByTestId('evaluation-table')).not.toBeInTheDocument();
  });

  it('an absent origin is an Unverified source, not Simulated', () => {
    const r = clone(CAPTURED_BASELINES_ONLY);
    delete r.origin;
    render(<EvaluationView result={r} />);
    expect(document.querySelector('[data-provenance-badge]')).toHaveAttribute('data-provenance-badge', 'unverified');
  });
});


const panel = () => screen.getByTestId('hard-constraints');
const hcRow = (id: string) => document.querySelector(`[data-hc-row="${id}"]`) as HTMLElement;
const hcCell = (row: string, limit: string) => hcRow(row).querySelector(`[data-hc-cell="${limit}"]`) as HTMLElement;

describe('Task 14: provenance and honesty labels on the evaluation view', () => {
  it('real legacy-0 report: violations are first-class, the PUE limit is "not measured" (never zero), executed physics is "not reported"', () => {
    render(<EvaluationView result={clone(CAPTURED_BASELINES_ONLY)} />);
    expect(screen.getByTestId('hard-constraints-headline')).toHaveTextContent(/Hard-constraint violations: 2 of 2 policies violate/);
    const rule = hcRow('rule');
    expect(rule).toHaveAttribute('data-hc-state', 'violated');
    expect(within(rule).getByText('Violates 1 of 4 limits')).toBeInTheDocument(); // words, not colour
    expect(rule.querySelector('[data-hc-icon="violated"]')).not.toBeNull(); // plus a distinct icon shape
    expect(hcCell('rule', 'inlet_under_min_steps')).toHaveTextContent('288 steps/episode — violated');
    expect(hcCell('rule', 'pue_over_max_steps')).toHaveTextContent('not measured');
    expect(hcCell('rule', 'pue_over_max_steps')).toHaveAttribute('data-hc-cell-state', 'not_measured');
    expect(hcCell('rule', 'outlet_violation_steps')).toHaveTextContent('0 — none');
    const identity = screen.getByTestId('evaluation-identity');
    expect(within(identity).getByText('Physics executed').closest('[data-identity]')).toHaveAttribute('data-reported', 'false');
    expect(within(identity).getByText(/not reported \(written before/)).toBeInTheDocument();
    expect(within(identity).getByText('legacy-0 (implicit)')).toBeInTheDocument(); // the registered label stays visible
    expect(within(identity).getByText('Assumed: flat constant, not a real grid series')).toBeInTheDocument();
    expect(within(identity).getByText('baselines_only_0fcafef9d28fd539')).toBeInTheDocument();
  });

  it('the panel comes before the metrics table and is not styled as success or failure by colour', () => {
    const { container } = render(<EvaluationView result={syntheticSchema2()} />);
    const order = [...container.querySelectorAll('[data-testid="outcome-headline"], [data-testid="hard-constraints"], [data-testid="evaluation-table"]')].map((e) => e.getAttribute('data-testid'));
    expect(order).toEqual(['outcome-headline', 'hard-constraints', 'evaluation-table']);
    expect(panel().outerHTML).not.toMatch(/green|success|emerald|red-|destructive/);
  });

  it('schema 2, every limit measured and zero: "clean" is allowed and states what it covers', () => {
    render(<EvaluationView result={syntheticSchema2()} />);
    expect(screen.getByTestId('hard-constraints-headline')).toHaveTextContent('No policy violated any counted hard limit on the test episodes.');
    expect(hcRow('rule')).toHaveAttribute('data-hc-state', 'clean');
    expect(hcCell('rule', 'pue_over_max_steps')).toHaveTextContent('0 — none');
    expect(panel()).toHaveAttribute('data-violating-policies', '0');
    expect(screen.queryByTestId('comparator-caveat')).toBeNull();
  });

  it('a PUE-only violation is shown and names the limit', () => {
    render(<EvaluationView result={withMetric(syntheticSchema2(), 'best_constant', 'pue_over_max_steps', 3.5)} />);
    expect(hcRow('best_constant')).toHaveAttribute('data-hc-state', 'violated');
    expect(hcRow('rule')).toHaveAttribute('data-hc-state', 'clean');
    expect(hcCell('best_constant', 'pue_over_max_steps')).toHaveTextContent('3.5 steps/episode — violated');
    expect(screen.getByTestId('hard-constraints-headline')).toHaveTextContent('1 of 2 policies violate');
  });

  it('an unmeasured limit can never read as clean, and the backend note is shown verbatim', () => {
    const r = withMetric(syntheticSchema2(), 'rule', 'pue_over_max_steps', undefined);
    r.hard_constraints = { counted: [], not_measured: ['pue_over_max_steps'], note: 'Older schema: PUE not counted.' };
    render(<EvaluationView result={r} />);
    expect(hcRow('rule')).toHaveAttribute('data-hc-state', 'partial');
    expect(within(hcRow('rule')).getByText(/No violation in the 3 measured limits; 1 not measured/)).toBeInTheDocument();
    expect(screen.getByTestId('hard-constraints-note')).toHaveTextContent('Older schema: PUE not counted.');
    expect(screen.getByTestId('hard-constraints-headline')).toHaveTextContent(/not the same as zero/);
  });

  it('the backend says not_measured even when a metric key is present: it is still "not measured"', () => {
    const r = syntheticSchema2();
    r.hard_constraints = { counted: [], not_measured: ['pue_over_max_steps'] };
    render(<EvaluationView result={r} />);
    expect(hcCell('rule', 'pue_over_max_steps')).toHaveAttribute('data-hc-cell-state', 'not_measured');
  });

  it('an infeasible best-constant comparator is stated', () => {
    const r = syntheticSchema2();
    r.selection = { best_constant_envelope_feasible: false };
    render(<EvaluationView result={r} />);
    expect(screen.getByTestId('comparator-caveat')).toHaveTextContent(/no constant set-point satisfied every hard limit/i);
  });

  it('shows the executed physics, and both labels when they differ', () => {
    render(<EvaluationView result={syntheticSchema2({ physics_version: 'legacy-0 (implicit)', physics_version_executed: 'legacy-0' })} />);
    const identity = screen.getByTestId('evaluation-identity');
    expect(within(identity).getByText('legacy-0 (registered as "legacy-0 (implicit)")')).toBeInTheDocument();
  });

  it('the strip carries the run id, the simulator origin and the fallback-carbon flag; measured carbon shows no fallback flag', () => {
    const { unmount } = render(<EvaluationView result={syntheticSchema2()} />);
    expect(document.querySelector('[data-provenance-run]')).toHaveTextContent('Run synthetic_schema2');
    expect(document.querySelector('[data-provenance-badge]')).toHaveAttribute('data-provenance-badge', 'simulated');
    expect(document.querySelector('[data-flag="fallback"]')).not.toBeNull();
    unmount();
    render(<EvaluationView result={syntheticSchema2({ carbon: { is_real: true, flat_curve: false } })} />);
    expect(document.querySelector('[data-flag="fallback"]')).toBeNull();
    expect(within(screen.getByTestId('evaluation-identity')).getByText(/Measured series/)).toBeInTheDocument();
  });

  it('carbon information missing entirely reads "not reported", never "real" and never a fallback claim', () => {
    const r = syntheticSchema2();
    delete r.carbon;
    render(<EvaluationView result={r} />);
    const carbonRow = within(screen.getByTestId('evaluation-identity')).getByText('Carbon signal').closest('[data-identity]');
    expect(carbonRow).toHaveTextContent('not reported');
    expect(carbonRow).toHaveAttribute('data-reported', 'false');
    expect(document.querySelector('[data-flag="fallback"]')).toBeNull();
  });

  it('NOT_EVALUATED stays a plain neutral banner next to the constraint panel (never styled as success)', () => {
    const { container } = render(<EvaluationView result={syntheticSchema2()} />);
    expect(container.querySelector('[data-outcome="NOT_EVALUATED"]')).not.toBeNull();
    expect(screen.getByTestId('outcome-headline')).toHaveTextContent('Not evaluated');
    expect(container.innerHTML).not.toMatch(/bg-green|text-green|success/);
  });

  it('no policies: no constraint table and no clean claim', () => {
    render(<EvaluationView result={syntheticSchema2({ policies: [] })} />);
    expect(screen.getByTestId('hard-constraints-headline')).toHaveTextContent('No policies reported');
    expect(screen.queryByTestId('hard-constraints-table')).toBeNull();
  });
});
