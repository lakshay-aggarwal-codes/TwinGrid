import { AlertTriangle, CheckCircle2, Clock, HelpCircle, WifiOff, XOctagon, type LucideIcon } from 'lucide-react';
import type { SignalState } from '@/contract/signalState';
import { signalView, type FormatOptions, type SignalIcon } from './signalView';

const ICON: Record<SignalIcon, LucideIcon> = { ok: CheckCircle2, warning: AlertTriangle, critical: XOctagon, stale: Clock, offline: WifiOff, unknown: HelpCircle };

// Colour is a hint only: every status has its own icon SHAPE, its own text and its own border style (solid / dashed / dotted / double).
// `stale`, `offline` and `unknown` are deliberately neutral: an old or missing number is never styled as healthy.
const CLASS: Record<SignalIcon, string> = {
  ok: 'border-solid border-success/50 bg-success/10 text-success',
  warning: 'border-dashed border-warning/50 bg-warning/15 text-warning',
  critical: 'border-solid border-2 border-destructive/50 bg-destructive/15 text-destructive-text',
  stale: 'border-dashed border-muted-foreground/60 bg-muted text-muted-foreground',
  offline: 'border-dotted border-muted-foreground/60 bg-muted text-muted-foreground',
  unknown: 'border-double border-muted-foreground/60 bg-muted text-muted-foreground',
};

interface Props extends FormatOptions {
  readonly state: SignalState;
  /** Show the number beside the label (a stale number is always prefixed "last known" and given its age). Default: true. */
  readonly showValue?: boolean;
}

/** One signal's state: icon + text always; the number only when the policy allows it (never for offline / unknown). */
export function SignalStateBadge({ state, showValue = true, ...format }: Props) {
  const view = signalView(state, format);
  const Icon = ICON[view.icon];
  return (
    <span
      data-testid="signal-state-badge"
      data-status={view.status}
      data-reason={state.reason_code}
      data-current={view.isCurrent ? 'true' : 'false'}
      title={view.description}
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium ${CLASS[view.icon]}`}
    >
      <Icon aria-hidden="true" className="h-3 w-3" />
      <span className="uppercase tracking-wide">{view.label}</span>
      {showValue && view.valueText !== null && (
        <span data-testid="signal-state-value" data-value-kind={view.isCurrent ? 'current' : 'last-known'} className="font-mono normal-case">
          {view.isCurrent ? view.valueText : `last known ${view.valueText}${view.ageText ? ` · ${view.ageText}` : ''}`}
        </span>
      )}
      <span className="sr-only">{view.description}</span>
    </span>
  );
}
