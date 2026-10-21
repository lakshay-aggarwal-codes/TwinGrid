/** Task 16: Python/TypeScript parity on `tests/fixtures/signal_state_cases.json`, plus the properties the badges rely on. */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  DEFAULT_SIGNAL_RULES,
  SIGNAL_REASON_CODES,
  SIGNAL_STATUSES,
  evaluateSignal,
  formatInstant,
  instantMs,
  signalUnavailable,
  staleAfterSeconds,
  type SignalRule,
} from './signalState';

interface Case {
  id: string;
  description: string;
  input: { value: number | null; observed_at: string | null; now: string; rule: SignalRule; stale_after_s: number; connected: boolean };
  expected: Record<string, unknown>;
}
interface Doc {
  cases: Case[];
  default_rules: Record<string, { crit_low?: number; crit_high?: number; unit: string }>;
  stale_after: Array<{ interval_s: number | null; expected_s: number }>;
}

// vitest runs with the package as cwd: <repo>/twin-stream-insight-main -> ../tests/fixtures
const DOC = JSON.parse(readFileSync(resolve(process.cwd(), '../tests/fixtures/signal_state_cases.json'), 'utf-8')) as Doc;
const NOW = '2026-10-20T10:10:00Z';
const BAND: SignalRule = { rule_id: 'band', warn_low: 20, warn_high: 25, crit_low: 15, crit_high: 30, unit: '°C' };
const secondsAgo = (s: number) => Date.parse(NOW) - s * 1000;

describe('shared fixture parity with src/signal_state.py', () => {
  it.each(DOC.cases.map((c) => [c.id, c] as const))('%s', (_id, c) => {
    const i = c.input;
    expect(evaluateSignal(i.value, i.observed_at, i.now, i.rule, i.stale_after_s, i.connected)).toEqual(c.expected);
  });

  it('covers every status and every reason code except the adapter one', () => {
    expect(new Set(DOC.cases.map((c) => c.expected.status))).toEqual(new Set(SIGNAL_STATUSES));
    expect(new Set(DOC.cases.map((c) => c.expected.reason_code))).toEqual(new Set(SIGNAL_REASON_CODES.filter((r) => r !== 'rule_unavailable')));
  });

  it('keeps the stale window equal to the shared table (and to hooks/liveness.ts)', () => {
    for (const row of DOC.stale_after) expect(staleAfterSeconds(row.interval_s)).toBe(row.expected_s);
    expect(staleAfterSeconds(Number.NaN)).toBe(9);
  });
});

describe('properties', () => {
  it('an old reading is never normal, warning or critical', () => {
    for (const value of [-1e9, 0, 14.9, 19.9, 22, 25.1, 30.1, 1e9]) {
      for (const age of [10.001, 11, 3600, 1e7]) {
        const s = evaluateSignal(value, secondsAgo(age), NOW, BAND, 10);
        expect(s.status).toBe('stale');
        expect(s.threshold).toBeNull();
      }
    }
  });

  it('unknown and offline never carry a number', () => {
    for (const connected of [true, false]) {
      for (const observed of [null, secondsAgo(1), secondsAgo(86400 * 3)]) {
        const s = evaluateSignal(null, observed, NOW, BAND, 10, connected);
        expect(s.status).toBe(connected ? 'unknown' : 'offline');
        expect(s.value).toBeNull();
      }
    }
  });

  it('treats NaN / Infinity / undefined as no value, like Python', () => {
    for (const v of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, undefined]) {
      expect(evaluateSignal(v, NOW, NOW, BAND, 10).status).toBe('unknown');
      expect(evaluateSignal(v, NOW, NOW, BAND, 10, false).status).toBe('offline');
    }
  });

  it('a number with no (or an unreadable) observation time is not shown as current', () => {
    for (const obs of [null, undefined, 'not a time', Number.NaN]) {
      const s = evaluateSignal(22, obs, NOW, BAND, 10);
      expect([s.status, s.reason_code, s.value, s.age_s]).toEqual(['unknown', 'no_value', null, null]);
    }
  });

  it('accepts epoch ms, Date and offset strings as the same instant', () => {
    const ms = Date.parse('2026-10-20T10:09:58Z');
    const forms = [ms, new Date(ms), '2026-10-20T10:09:58Z', '2026-10-20T15:39:58+05:30'];
    const states = forms.map((f) => evaluateSignal(22, f, NOW, BAND, 10));
    for (const s of states) expect(s).toEqual(states[0]);
    expect(states[0].observed_at).toBe('2026-10-20T10:09:58Z');
  });

  it('formats instants canonically', () => {
    expect(formatInstant(Date.UTC(2026, 0, 2, 3, 4, 5))).toBe('2026-01-02T03:04:05Z');
    expect(formatInstant(Date.UTC(2026, 0, 2, 3, 4, 5, 120))).toBe('2026-01-02T03:04:05.120Z');
    expect(formatInstant(null)).toBeNull();
    expect(instantMs('garbage')).toBeNull();
  });

  it('signalUnavailable is unknown / rule_unavailable with no number', () => {
    expect(signalUnavailable('x', 'kW')).toEqual({
      status: 'unknown', reason_code: 'rule_unavailable', rule_id: 'x', value: null, threshold: null, observed_at: null, age_s: null, unit: 'kW',
    });
  });

  it('DEFAULT_SIGNAL_RULES equal the fixture default_rules (inlet 18-27, outlet 45, PUE 2.0 from SAFETY_ENVELOPE) and have no warning band', () => {
    for (const [id, raw] of Object.entries(DOC.default_rules)) {
      const rule = DEFAULT_SIGNAL_RULES[id as keyof typeof DEFAULT_SIGNAL_RULES];
      expect({ crit_low: rule.crit_low, crit_high: rule.crit_high, unit: rule.unit }).toEqual({ crit_low: raw.crit_low, crit_high: raw.crit_high, unit: raw.unit });
      expect(rule.warn_low ?? null).toBeNull();
      expect(rule.warn_high ?? null).toBeNull();
    }
    expect(Object.keys(DEFAULT_SIGNAL_RULES).sort()).toEqual(Object.keys(DOC.default_rules).sort());
  });
});
