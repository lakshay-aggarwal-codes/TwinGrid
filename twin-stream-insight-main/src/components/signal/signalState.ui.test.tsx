/** Task 16: the UI side of the signal-state policy: stale is never green, offline/unknown never show a number, colour is never alone. */
import { describe, expect, it } from 'vitest';
import { render, screen, within, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DEFAULT_SIGNAL_RULES, evaluateSignal, SIGNAL_STATUSES, type SignalState, type SignalStatus } from '@/contract/signalState';
import { feedIn } from '@/three/feedTestUtils.ts';
import { alertRow } from '@/components/alerts/alertFixtures';
import { AlertRowItem } from '@/components/alerts/AlertRowItem';
import { ThermalLegend } from '@/components/shell/ThermalLegend';
import { AlertRuleFacts } from './AlertRuleFacts';
import { SignalStateBadge } from './SignalStateBadge';
import { signalView, stateFromAgedReading } from './signalView';

const NOW = Date.parse('2026-10-20T10:10:00Z');
const RULE = DEFAULT_SIGNAL_RULES.inlet_temp_c;
const at = (s: number) => NOW - s * 1000;
const STATES: Record<SignalStatus, SignalState> = {
  normal: evaluateSignal(22, at(1), NOW, RULE, 10),
  warning: { ...evaluateSignal(22, at(1), NOW, RULE, 10), status: 'warning', reason_code: 'above_warn', threshold: 25 },
  critical: evaluateSignal(28.5, at(1), NOW, RULE, 10),
  stale: evaluateSignal(22, at(120), NOW, RULE, 10),
  offline: evaluateSignal(null, null, NOW, RULE, 10, false),
  unknown: evaluateSignal(null, null, NOW, RULE, 10, true),
};

describe('signalView', () => {
  it('labels every status and shows numbers only where the policy allows', () => {
    const v = Object.fromEntries(SIGNAL_STATUSES.map((s) => [s, signalView(STATES[s])])) as Record<SignalStatus, ReturnType<typeof signalView>>;
    expect(v.normal).toMatchObject({ label: 'Normal', valueText: '22.0 °C', isCurrent: true, ageText: null });
    expect(v.critical).toMatchObject({ label: 'Critical', valueText: '28.5 °C', isCurrent: true });
    expect(v.stale).toMatchObject({ label: 'Stale', valueText: '22.0 °C', isCurrent: false, ageText: '2 min ago' });
    expect(v.offline).toMatchObject({ label: 'Offline', valueText: null, isCurrent: false });
    expect(v.unknown).toMatchObject({ label: 'Unknown', valueText: null, isCurrent: false });
  });

  it('describes each state in one sentence that never calls a stale or missing value current', () => {
    expect(signalView(STATES.critical).description).toBe('inlet_temp_c: critical, 28.5 °C is above 27.0 °C.');
    expect(signalView(STATES.stale).description).toContain('last known 22.0 °C, 2 min ago');
    expect(signalView(STATES.stale).description).toContain('not a current reading');
    expect(signalView(STATES.offline).description).toBe('inlet_temp_c: offline, no current value.');
    expect(signalView({ ...STATES.unknown, reason_code: 'rule_unavailable' }).description).toContain('no rule is available');
  });

  it('honours decimals and unit overrides', () => {
    expect(signalView(evaluateSignal(1.234, at(1), NOW, DEFAULT_SIGNAL_RULES.pue, 10), { decimals: 2 }).valueText).toBe('1.23');
    expect(signalView(STATES.normal, { unit: '°F' }).valueText).toBe('22.0 °F');
  });
});

describe('stateFromAgedReading', () => {
  const base = { staleAfterS: 9, connected: true };
  it('live feed, fresh value: the policy decides', () => {
    expect(stateFromAgedReading(RULE, { ...base, value: 20, ageMs: 500, feedNotLive: false }).status).toBe('normal');
    expect(stateFromAgedReading(RULE, { ...base, value: 30, ageMs: 500, feedNotLive: false }).status).toBe('critical');
  });
  it('live feed but older than the window: stale', () => {
    expect(stateFromAgedReading(RULE, { ...base, value: 20, ageMs: 9_001, feedNotLive: false }).status).toBe('stale');
  });
  it('a feed that is not live is ALWAYS stale, whatever the value and however young the age', () => {
    for (const value of [10, 20, 30]) for (const ageMs of [0, 1, 500, 42_000]) expect(stateFromAgedReading(RULE, { ...base, value, ageMs, feedNotLive: true }).status).toBe('stale');
  });
  it('no frame: unknown while connecting, offline otherwise; never a number', () => {
    const none = { value: null, ageMs: null, feedNotLive: true, staleAfterS: 9 };
    expect(stateFromAgedReading(RULE, { ...none, connected: true })).toMatchObject({ status: 'unknown', value: null });
    expect(stateFromAgedReading(RULE, { ...none, connected: false })).toMatchObject({ status: 'offline', value: null });
  });
  it('never invents an observation instant', () => {
    expect(stateFromAgedReading(RULE, { ...base, value: 20, ageMs: 500, feedNotLive: false }).observed_at).toBeNull();
  });
});

describe('SignalStateBadge', () => {
  it.each(SIGNAL_STATUSES)('%s: icon + visible text + an accessible sentence; colour is not the only cue', (status) => {
    const { container } = render(<SignalStateBadge state={STATES[status]} />);
    const badge = screen.getByTestId('signal-state-badge');
    expect(badge).toHaveAttribute('data-status', status);
    expect(container.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
    expect(badge.textContent?.toLowerCase()).toContain(status);
    expect(badge.querySelector('.sr-only')?.textContent).toBe(signalView(STATES[status]).description);
    expect(badge).toHaveAttribute('title', signalView(STATES[status]).description);
  });

  it('every status has its own border style or width, so no two are told apart by colour alone', () => {
    const cues = new Set<string>();
    for (const status of SIGNAL_STATUSES) {
      const { unmount } = render(<SignalStateBadge state={STATES[status]} />);
      const cls = screen.getByTestId('signal-state-badge').className;
      cues.add(`${/border-(solid|dashed|dotted|double)/.exec(cls)?.[1]}|${cls.includes('border-2')}|${status === 'normal' || status === 'warning' || status === 'critical' ? status : 'neutral'}`);
      unmount();
    }
    const nonCurrent = ['stale', 'offline', 'unknown'].map((s) => {
      const { unmount } = render(<SignalStateBadge state={STATES[s as SignalStatus]} />);
      const style = /border-(solid|dashed|dotted|double)/.exec(screen.getByTestId('signal-state-badge').className)?.[1];
      unmount();
      return style;
    });
    expect(new Set(nonCurrent).size).toBe(3); // stale, offline and unknown differ from each other by border style as well as by icon + text
    expect(cues.size).toBe(SIGNAL_STATUSES.length);
  });

  it.each(['stale', 'offline', 'unknown'] as const)('%s is never styled as healthy', (status) => {
    render(<SignalStateBadge state={STATES[status]} />);
    const cls = screen.getByTestId('signal-state-badge').className;
    expect(cls).not.toMatch(/success|green/);
    expect(cls).toContain('text-muted-foreground');
  });

  it('a current number is plain; a stale number is "last known" with its age; offline / unknown show no number', () => {
    const { unmount } = render(<SignalStateBadge state={STATES.normal} />);
    expect(screen.getByTestId('signal-state-value')).toHaveAttribute('data-value-kind', 'current');
    expect(screen.getByTestId('signal-state-value')).toHaveTextContent('22.0 °C');
    unmount();
    const stale = render(<SignalStateBadge state={STATES.stale} />);
    expect(screen.getByTestId('signal-state-value')).toHaveAttribute('data-value-kind', 'last-known');
    expect(screen.getByTestId('signal-state-value')).toHaveTextContent('last known 22.0 °C · 2 min ago');
    stale.unmount();
    for (const s of ['offline', 'unknown'] as const) {
      const r = render(<SignalStateBadge state={STATES[s]} />);
      expect(screen.queryByTestId('signal-state-value')).toBeNull();
      expect(screen.getByTestId('signal-state-badge').textContent).not.toMatch(/\d/);
      r.unmount();
    }
  });

  it('showValue=false hides the number but keeps the state', () => {
    render(<SignalStateBadge state={STATES.normal} showValue={false} />);
    expect(screen.queryByTestId('signal-state-value')).toBeNull();
    expect(screen.getByTestId('signal-state-badge')).toHaveAttribute('data-status', 'normal');
  });
});

describe('ThermalLegend wiring', () => {
  const statuses = () => screen.getAllByTestId('signal-state-badge').map((b) => b.getAttribute('data-status'));

  it('live: inlet 20.0 and outlet 30.0 are within the envelope -> normal, current', () => {
    render(<ThermalLegend feed={feedIn('live')} />);
    expect(statuses()).toEqual(['normal', 'normal']);
  });

  it('live and outside the envelope -> critical for the one that crossed', () => {
    render(<ThermalLegend feed={feedIn('live', { state: { server_inlet_temp_C: 28, server_outlet_temp_C: 46 } })} />);
    expect(statuses()).toEqual(['critical', 'critical']);
  });

  it.each(['stale', 'disconnected', 'reconnecting'] as const)('%s: last-known readings are stale, never normal, with the age in the badge text', (state) => {
    render(<ThermalLegend feed={feedIn(state)} />);
    expect(statuses()).toEqual(['stale', 'stale']);
    for (const b of screen.getAllByTestId('signal-state-badge')) expect(b).toHaveAttribute('data-current', 'false');
    expect(screen.getByTestId('thermal-legend').innerHTML).not.toMatch(/bg-success|text-success|border-success/);
  });

  it('a stale reading that is also out of range is stale, not a current alarm', () => {
    render(<ThermalLegend feed={feedIn('stale', { state: { server_inlet_temp_C: 40 } })} />);
    expect(statuses()[0]).toBe('stale');
  });

  it('connecting: unknown, no temperatures; unavailable: offline, no temperatures', () => {
    const a = render(<ThermalLegend feed={feedIn('connecting')} />);
    expect(statuses()).toEqual(['unknown', 'unknown']);
    expect(screen.queryByText(/°C$/)).toBeNull();
    a.unmount();
    render(<ThermalLegend feed={feedIn('unavailable')} />);
    expect(statuses()).toEqual(['offline', 'offline']);
    expect(screen.queryByText(/°C$/)).toBeNull();
  });
});

describe('AlertRuleFacts', () => {
  it('shows rule, value, threshold, observed_at, origin and evidence, with honest "not reported" gaps', () => {
    render(<AlertRuleFacts ruleId="reconstruction_error" value={0.1234} valueLabel="Value (detector score)" threshold={null} observedAt="2026-10-06 10:00:00 UTC" origin={null} />);
    const facts = screen.getByTestId('alert-rule-facts');
    expect(within(facts).getByTestId('rule-id')).toHaveTextContent('reconstruction_error');
    expect(within(facts).getByTestId('rule-value')).toHaveTextContent('0.1234');
    expect(within(facts).getByTestId('rule-threshold')).toHaveTextContent('not reported');
    expect(within(facts).getByTestId('rule-observed-at')).toHaveTextContent('2026-10-06 10:00:00 UTC');
    expect(within(facts).getByTestId('rule-origin')).toHaveTextContent('not reported (Unverified source)');
    expect(within(facts).getByTestId('rule-evidence')).toHaveTextContent('all that is stored with this alert');
    expect(screen.getByRole('region', { name: 'Rule that raised this alert' })).toBe(facts);
  });

  it('shows a threshold and an evidence link when the page supplies them', () => {
    render(<AlertRuleFacts ruleId="r" value={1} valueLabel="Value" threshold={0.01} observedAt={null} origin="simulated" evidence={<a href="#e">Open evidence</a>} />);
    expect(screen.getByTestId('rule-threshold')).toHaveTextContent('0.0100');
    expect(screen.getByTestId('rule-observed-at')).toHaveTextContent('not reported');
    expect(screen.getByTestId('rule-origin')).toHaveTextContent('simulated');
    expect(screen.getByRole('link', { name: 'Open evidence' })).toBeInTheDocument();
  });
});

describe('AlertRowItem evidence panel', () => {
  it('mounts the rule facts once expanded, from the alert record only', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ul>
          <AlertRowItem alert={alertRow({ id: 7, origin: null })} role="viewer" queryKey={['alerts']} onSelect={() => undefined} />
        </ul>
      </QueryClientProvider>,
    );
    expect(screen.queryByTestId('alert-rule-facts')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /detection 7/ }));
    expect(screen.getByTestId('rule-id')).toHaveTextContent('reconstruction_error');
    expect(screen.getByTestId('rule-value')).toHaveTextContent('0.1234');
    expect(screen.getByTestId('rule-observed-at')).toHaveTextContent('2026-10-06 10:00:00 UTC');
    expect(screen.getByTestId('rule-origin')).toHaveTextContent('Unverified source');
  });
});
