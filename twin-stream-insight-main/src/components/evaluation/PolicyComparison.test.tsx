import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { CAPTURED_BASELINES_ONLY, clone, syntheticSchema2, syntheticWithPpo, withMetric } from '@/evaluation/testFixtures';
import type { EvaluationResult } from '@/evaluation/schema';
import { EvaluationView } from './EvaluationView';
import { PolicyComparison } from './PolicyComparison';

afterEach(cleanup);

const withEnvelope = (ok: boolean, extra: Record<string, number> = {}): EvaluationResult =>
  syntheticWithPpo('B', {
    decision: {
      outcome: 'B',
      claim_allowed: 'none',
      reason: 'SYNTHETIC reason',
      detail: {
        per_baseline: { rule: { baseline_envelope_safe: false, seed_level_diff: { n: 5, mean: -1, ci_low: -2, ci_high: 0 } } },
        envelope_selected_candidate: { ok, outlet_violation_steps: 0, inlet_over_max_steps: 0, inlet_under_min_steps: 0, ...extra },
      },
    },
  });

const section = () => screen.getByTestId('policy-comparison');
const refSelect = () => screen.getByLabelText('Reference policy') as HTMLSelectElement;
const cmpSelect = () => screen.getByLabelText('Compared policy') as HTMLSelectElement;

describe('PolicyComparison (Task 14/16)', () => {
  it('is part of the evaluation view, after the table, with labelled selects and neutral defaults', () => {
    const { container } = render(<EvaluationView result={withEnvelope(true)} />);
    const order = [...container.querySelectorAll('[data-testid="evaluation-table"], [data-testid="policy-comparison"]')].map((e) => e.getAttribute('data-testid'));
    expect(order).toEqual(['evaluation-table', 'policy-comparison']);
    expect(refSelect().value).toBe('rule');
    expect(cmpSelect().value).toBe('ppo_seed_0');
    // the backend's order in both lists, never sorted; the PPO row is marked by its kind
    const values = (sel: HTMLSelectElement) => [...sel.options].map((o) => o.value);
    expect(values(refSelect())).toEqual(['rule', 'best_constant', 'ppo_seed_0']);
    expect(values(cmpSelect())).toEqual(['rule', 'best_constant', 'ppo_seed_0']);
    expect([...cmpSelect().options].at(-1)?.textContent).toBe('ppo_seed_0 (ppo)');
  });

  it('shows hard constraints before the metrics, then the table with hard rows first', () => {
    const { container } = render(<PolicyComparison result={withEnvelope(true)} />);
    const blocks = [...container.querySelectorAll('[data-testid="comparison-constraints"], [data-testid="comparison-table"]')].map((e) => e.getAttribute('data-testid'));
    expect(blocks).toEqual(['comparison-constraints', 'comparison-table']);
    const groups = [...container.querySelectorAll('[data-cmp-row]')].map((r) => r.getAttribute('data-cmp-group'));
    expect(groups.slice(0, 4)).toEqual(['hard', 'hard', 'hard', 'hard']);
    expect(groups.slice(4).every((g) => g === 'other')).toBe(true);
    expect(screen.getByTestId('comparison-table').querySelector('caption')).toHaveTextContent('Reference rule vs compared ppo_seed_0');
  });

  it('names what decided the outcome when the selected candidate violated a limit', () => {
    render(<PolicyComparison result={withEnvelope(false, { inlet_under_min_steps: 3 })} />);
    expect(screen.getByTestId('comparison-candidate-violations')).toHaveTextContent('Inlet under minimum (3 steps/episode)');
    expect(screen.getByTestId('comparison-candidate-violations')).toHaveTextContent('excludes outcome A, whatever its reward');
    expect(screen.getByTestId('comparison-deciding')).toHaveTextContent('Baselines the report judged not envelope-safe: rule');
    expect(screen.getByTestId('comparison-deciding')).toHaveTextContent('SYNTHETIC reason');
  });

  it('a candidate within the envelope is stated as such, not as a win', () => {
    render(<PolicyComparison result={withEnvelope(true)} />);
    expect(screen.getByTestId('comparison-deciding')).toHaveTextContent('stayed within every counted hard limit');
    expect(section().textContent).not.toMatch(/\bwinner\b|\bbest\b performing|\bbetter overall\b/i);
  });

  it('real baselines-only report: no PPO decision detail, no interval, both baselines violate', () => {
    render(<PolicyComparison result={clone(CAPTURED_BASELINES_ONLY)} />);
    expect(screen.getByTestId('comparison-deciding')).toHaveTextContent('no PPO decision detail');
    expect(screen.getByTestId('comparison-eligibility')).toHaveTextContent(/^Both policies violate at least one hard limit/);
    expect(screen.getByTestId('comparison-uncertainty')).toHaveTextContent('uncertainty not provided');
    expect(document.querySelector('[data-cmp-row="pue_over_max_steps"]')).toHaveTextContent('not provided');
    expect(document.querySelector('[data-cmp-constraint="rule"] [data-hc-icon="violated"]')).not.toBeNull(); // words + icon shape
  });

  it('changing a select updates the comparison; choosing the same policy twice says so and shows no numbers', () => {
    render(<PolicyComparison result={withEnvelope(true)} />);
    fireEvent.change(cmpSelect(), { target: { value: 'best_constant' } });
    expect(screen.getByTestId('comparison-table').querySelector('caption')).toHaveTextContent('compared best_constant');
    expect(screen.getByTestId('comparison-uncertainty')).toHaveTextContent('uncertainty not provided'); // not a PPO-vs-baseline pair
    fireEvent.change(cmpSelect(), { target: { value: 'rule' } });
    expect(screen.getByTestId('comparison-problem')).toHaveTextContent('Choose two different policies.');
    expect(screen.queryByTestId('comparison-table')).toBeNull();
    fireEvent.change(cmpSelect(), { target: { value: 'ppo_seed_0' } });
    expect(screen.getByTestId('comparison-uncertainty')).toHaveTextContent('none are computed here');
    expect(screen.getByText(/training seeds \(n=5\)/)).toBeInTheDocument();
  });

  it('shows a PUE-only violation of the compared policy in the eligibility sentence', () => {
    render(<PolicyComparison result={withMetric(syntheticSchema2(), 'best_constant', 'pue_over_max_steps', 2)} />);
    expect(screen.getByTestId('comparison-eligibility')).toHaveTextContent(/compared policy violates/);
    expect(document.querySelector('[data-cmp-row="pue_over_max_steps"] [data-cmp-diff]')).toHaveTextContent('2');
  });

  it('with fewer than two policies there is nothing to compare, and no selects', () => {
    render(<PolicyComparison result={{ ...clone(CAPTURED_BASELINES_ONLY), policies: clone(CAPTURED_BASELINES_ONLY).policies.slice(0, 1) }} />);
    expect(screen.getByTestId('comparison-unavailable')).toHaveTextContent('fewer than two policies');
    expect(screen.queryByLabelText('Reference policy')).toBeNull();
  });

  it('uses neutral styling: no success/failure colours, no sorting or ranking markers', () => {
    const { container } = render(<PolicyComparison result={withEnvelope(false, { inlet_under_min_steps: 3 })} />);
    expect(container.innerHTML).not.toMatch(/green|success|emerald|red-|destructive|bg-primary/);
  });

  it('a different report starts from its own defaults (keyed by report id)', () => {
    const a = withEnvelope(true);
    const b = { ...syntheticSchema2(), evaluation_id: 'other_report' };
    const { rerender } = render(<EvaluationView result={a} />);
    fireEvent.change(cmpSelect(), { target: { value: 'best_constant' } });
    rerender(<EvaluationView result={b} />);
    expect(refSelect().value).toBe('rule');
    expect(cmpSelect().value).toBe('best_constant'); // b has no PPO row: its own default (second policy), not a stale selection
  });
});
