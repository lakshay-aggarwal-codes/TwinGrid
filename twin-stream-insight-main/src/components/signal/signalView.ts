/**
 * Task 16: view model for a `SignalState` (contract/signalState.ts). Pure; no React.
 *
 * Rules the UI keeps (each is tested): meaning is carried by icon SHAPE + text + border style, never by colour alone; a `stale`
 * reading is never green and is always shown as "last known" with its age; `offline` and `unknown` never show a number.
 */
import { evaluateSignal, type SignalRule, type SignalState, type SignalStatus } from '@/contract/signalState';
import { formatAge } from '@/provenance';

export type SignalIcon = 'ok' | 'warning' | 'critical' | 'stale' | 'offline' | 'unknown';

export interface SignalView {
  readonly status: SignalStatus;
  readonly icon: SignalIcon;
  /** Visible text of the badge. */
  readonly label: string;
  /** The number as it may be shown, or null when no number may be shown (offline / unknown). */
  readonly valueText: string | null;
  /** True only when the number is a CURRENT reading (normal / warning / critical). Stale is "last known". */
  readonly isCurrent: boolean;
  /** "42 s ago" for a stale reading; null otherwise. */
  readonly ageText: string | null;
  /** One sentence for assistive technology and tooltips. */
  readonly description: string;
}

const LABEL: Record<SignalStatus, string> = {
  normal: 'Normal',
  warning: 'Warning',
  critical: 'Critical',
  stale: 'Stale',
  offline: 'Offline',
  unknown: 'Unknown',
};

const ICON: Record<SignalStatus, SignalIcon> = { normal: 'ok', warning: 'warning', critical: 'critical', stale: 'stale', offline: 'offline', unknown: 'unknown' };

export interface FormatOptions {
  readonly decimals?: number;
  /** Overrides the rule's unit label (e.g. for display). */
  readonly unit?: string;
}

function numberText(value: number, unit: string, decimals: number): string {
  return unit ? `${value.toFixed(decimals)} ${unit}` : value.toFixed(decimals);
}

export function signalView(state: SignalState, options: FormatOptions = {}): SignalView {
  const decimals = options.decimals ?? 1;
  const unit = options.unit ?? state.unit;
  const status = state.status;
  const hasNumber = state.value !== null && (status === 'normal' || status === 'warning' || status === 'critical' || status === 'stale');
  const valueText = hasNumber && state.value !== null ? numberText(state.value, unit, decimals) : null;
  const ageText = status === 'stale' && state.age_s !== null ? formatAge(state.age_s * 1000) : null;
  const isCurrent = status === 'normal' || status === 'warning' || status === 'critical';

  let description: string;
  switch (status) {
    case 'normal':
      description = `${state.rule_id}: normal, ${valueText} is within its bounds.`;
      break;
    case 'warning':
    case 'critical':
      description = `${state.rule_id}: ${LABEL[status].toLowerCase()}, ${valueText}${state.threshold !== null ? ` is ${state.reason_code.startsWith('above') ? 'above' : 'below'} ${numberText(state.threshold, unit, decimals)}` : ''}.`;
      break;
    case 'stale':
      description = `${state.rule_id}: stale, last known ${valueText}${ageText ? `, ${ageText}` : ''}. This is not a current reading.`;
      break;
    case 'offline':
      description = `${state.rule_id}: offline, no current value.`;
      break;
    default:
      description = state.reason_code === 'rule_unavailable' ? `${state.rule_id}: unknown, no rule is available for this signal.` : `${state.rule_id}: unknown, no current value.`;
  }
  return { status, icon: ICON[status], label: LABEL[status], valueText, isCurrent, ageText, description };
}

export interface AgedReading {
  /** The last value received, or null if none. */
  readonly value: number | null;
  /** Milliseconds since it was received (monotonic), or null if no frame has ever arrived. */
  readonly ageMs: number | null;
  /** The feed's own freshness machine said the reading is not live (stale / disconnected / reconnecting). */
  readonly feedNotLive: boolean;
  /** The transport is up or still connecting (so "no value" is `unknown`); false means it is down (`offline`). */
  readonly connected: boolean;
  readonly staleAfterS: number;
}

/**
 * Policy state for a value the UI holds as "value + age" (no wall-clock timestamp). The age is the only time input, so the
 * evaluation runs on a relative timeline (observed at 0, now = age). When the feed machine has already decided the reading is
 * not live, the stale window is forced to -1 so that ANY age is stale: a last-known number can never come out as normal.
 */
export function stateFromAgedReading(rule: SignalRule, r: AgedReading): SignalState {
  const hasValue = r.value !== null && r.ageMs !== null;
  const window = r.feedNotLive ? -1 : r.staleAfterS;
  const s = evaluateSignal(hasValue ? r.value : null, hasValue ? 0 : null, hasValue ? (r.ageMs as number) : 0, rule, window, r.connected);
  return { ...s, observed_at: null }; // the relative timeline's "0" is not a real instant
}
