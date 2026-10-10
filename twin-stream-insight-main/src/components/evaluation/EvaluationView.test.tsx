import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CAPTURED_BASELINES_ONLY, SYNTHETIC_A, SYNTHETIC_B, SYNTHETIC_C, SYNTHETIC_UNKNOWN, clone, syntheticWithPpo } from '@/evaluation/testFixtures';

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
    expect(screen.getByText('Fallback carbon (flat constant)')).toBeInTheDocument();
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
