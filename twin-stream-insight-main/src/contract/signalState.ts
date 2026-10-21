/**
 * Signal state v1 (Task 16, playbook 8.5): the TypeScript mirror of `src/signal_state.py`. Both read
 * `tests/fixtures/signal_state_cases.json` and must return identical results for every case.
 *
 * Precedence (first match wins):
 *   1. no usable value (null/undefined/non-finite)  -> `unknown` (no_value) while connected, `offline` (disconnected) when not
 *   2. value but no observation time                -> `unknown` (no_value): freshness cannot be judged, so it is not shown as current
 *   3. observed_at ahead of now by more than FUTURE_TOLERANCE_S -> `unknown` (future): no number, age_s null. Ahead by at most
 *      the tolerance is clock skew and counts as age 0.
 *   4. age_s > stale_after_s                        -> `stale` (too_old): the value is kept as "last known" with its age
 *   5. a critical bound crossed                     -> `critical`
 *   6. a warning bound crossed                      -> `warning`
 *   7. otherwise                                    -> `normal`
 * A bound is crossed only by a STRICT comparison (same as `SafetyEnvelope.violations`). Stale beats critical on purpose:
 * an old number is never a current alarm and never green. Field names are snake_case, exactly as in the fixture/JSON.
 */
import { staleAfterMs } from '@/hooks/liveness';

/** Clock-skew allowance in seconds; mirrors `FUTURE_TOLERANCE_S` in `src/signal_state.py`. */
export const FUTURE_TOLERANCE_S = 5;

export const SIGNAL_STATUSES = ['normal', 'warning', 'critical', 'stale', 'offline', 'unknown'] as const;
export type SignalStatus = (typeof SIGNAL_STATUSES)[number];

export const SIGNAL_REASON_CODES = [
  'no_value',
  'future',
  'disconnected',
  'too_old',
  'above_crit',
  'below_crit',
  'above_warn',
  'below_warn',
  'within_bounds',
  'rule_unavailable',
] as const;
export type SignalReasonCode = (typeof SIGNAL_REASON_CODES)[number];

export interface SignalRule {
  readonly rule_id: string;
  readonly warn_low?: number | null;
  readonly warn_high?: number | null;
  readonly crit_low?: number | null;
  readonly crit_high?: number | null;
  readonly unit: string;
}

export interface SignalState {
  readonly status: SignalStatus;
  readonly reason_code: SignalReasonCode;
  readonly rule_id: string;
  readonly value: number | null;
  /** The bound that was crossed (warning / critical); null otherwise. */
  readonly threshold: number | null;
  /** Canonical UTC text: `YYYY-MM-DDTHH:MM:SS[.fff]Z` (milliseconds only when non-zero), or null. */
  readonly observed_at: string | null;
  readonly age_s: number | null;
  readonly unit: string;
}

/** An instant as epoch milliseconds, an ISO string with an offset, or a Date. Anything unreadable is treated as "no time". */
export type InstantInput = number | string | Date | null | undefined;

export function instantMs(input: InstantInput): number | null {
  if (input === null || input === undefined) return null;
  const ms = input instanceof Date ? input.getTime() : typeof input === 'number' ? input : Date.parse(input);
  return Number.isFinite(ms) ? ms : null;
}

/** Same canonical text as `isoformat_z` in Python. */
export function formatInstant(ms: number | null): string | null {
  if (ms === null) return null;
  return new Date(ms).toISOString().replace(/\.000Z$/, 'Z');
}

/** Stale window in seconds for a feed ticking every `intervalS` wall seconds: the browser's own rule (`hooks/liveness.ts`). */
export function staleAfterSeconds(intervalS?: number | null): number {
  return staleAfterMs(intervalS) / 1000;
}

const isNum = (v: number | null | undefined): v is number => typeof v === 'number' && Number.isFinite(v);

/** Classify one reading. Pure: no clock, no I/O. */
export function evaluateSignal(
  value: number | null | undefined,
  observedAt: InstantInput,
  now: InstantInput,
  rule: SignalRule,
  staleAfterS: number,
  connected = true,
): SignalState {
  const nowMs = instantMs(now);
  const obsMs = instantMs(observedAt);
  const deltaMs = obsMs !== null && nowMs !== null ? nowMs - obsMs : null;
  const future = deltaMs !== null && -deltaMs > FUTURE_TOLERANCE_S * 1000;
  const age = deltaMs !== null && !future ? Math.max(0, deltaMs) / 1000 : null;
  const base = { rule_id: rule.rule_id, observed_at: formatInstant(obsMs), age_s: age, unit: rule.unit } as const;
  const make = (status: SignalStatus, reason_code: SignalReasonCode, keepValue: boolean, threshold: number | null = null): SignalState => ({
    status,
    reason_code,
    value: keepValue && isNum(value) ? value : null,
    threshold,
    ...base,
  });

  if (!isNum(value)) return connected ? make('unknown', 'no_value', false) : make('offline', 'disconnected', false);
  if (obsMs === null || deltaMs === null) return make('unknown', 'no_value', false);
  if (future) return make('unknown', 'future', false);
  if (age === null) return make('unknown', 'no_value', false);
  if (age > staleAfterS) return make('stale', 'too_old', true);
  if (isNum(rule.crit_high) && value > rule.crit_high) return make('critical', 'above_crit', true, rule.crit_high);
  if (isNum(rule.crit_low) && value < rule.crit_low) return make('critical', 'below_crit', true, rule.crit_low);
  if (isNum(rule.warn_high) && value > rule.warn_high) return make('warning', 'above_warn', true, rule.warn_high);
  if (isNum(rule.warn_low) && value < rule.warn_low) return make('warning', 'below_warn', true, rule.warn_low);
  return make('normal', 'within_bounds', true);
}

/**
 * The default rules. The numbers are the existing safe operating envelope (`SAFETY_ENVELOPE` in `src/digital_twin.py`: inlet 18-27 °C,
 * outlet <= 45 °C, PUE <= 2.0); `signalState.test.ts` compares them with `default_rules` in the shared fixture, which a Python test
 * compares with the envelope itself. The repository defines no warning band, so there is none.
 */
export const DEFAULT_SIGNAL_RULES: Readonly<Record<'inlet_temp_c' | 'outlet_temp_c' | 'pue', SignalRule>> = {
  inlet_temp_c: { rule_id: 'inlet_temp_c', crit_low: 18, crit_high: 27, unit: '°C' },
  outlet_temp_c: { rule_id: 'outlet_temp_c', crit_high: 45, unit: '°C' },
  pue: { rule_id: 'pue', crit_high: 2, unit: '' },
};

/** What a caller returns when no rule exists for a signal: `unknown` / `rule_unavailable`, never a guess. */
export function signalUnavailable(ruleId: string, unit = ''): SignalState {
  return { status: 'unknown', reason_code: 'rule_unavailable', rule_id: ruleId, value: null, threshold: null, observed_at: null, age_s: null, unit };
}
