import type { ReactNode } from "react";
import {
  AlertTriangle,
  Ban,
  Clock,
  Cpu,
  CircleDashed,
  Info,
  Inbox,
  Loader2,
  Lock,
  ServerOff,
  WifiOff,
  type LucideIcon,
} from "lucide-react";
import { STATE_VOCABULARY, type UiStateKind } from "@/state/dataState";

interface StatusMessageProps {
  /** Any state in the FE-03 vocabulary. loading/error/empty are the original three. */
  kind: UiStateKind;
  children: ReactNode;
  /** Optional bold label (text cue in addition to the icon and colour), e.g. "Stale". */
  title?: string;
  /** Optional recovery action (e.g. Retry / Dismiss) -- error-like states only. */
  action?: { label: string; onClick: () => void };
  /** Centered block for whole-panel states (e.g. a list that has no content
   * yet); omit for inline states that sit inside an existing section. */
  block?: boolean;
}

/** One icon shape per state, so no state relies on colour alone. */
const ICONS: Record<UiStateKind, LucideIcon> = {
  loading: Loader2,
  empty: Inbox,
  not_run: CircleDashed,
  error: AlertTriangle,
  unauthorized: Lock,
  stale: Clock,
  disconnected: WifiOff,
  unavailable: ServerOff,
  incomplete: Info,
  unsupported_scenario: Ban,
  unavailable_model: Cpu,
};

const ALERT_STYLE = "rounded-md border border-destructive/40 bg-destructive/10 p-2.5 text-xs text-destructive";

/**
 * Stage 14: the one visual pattern for every loading / error / empty state in the app.
 * FE-03 extends it (it is not replaced) to the whole state vocabulary in `src/state/dataState.ts`:
 *  - role and live-region behaviour come from `STATE_VOCABULARY` (alert / status / none);
 *  - every state has a distinct icon plus text, never colour alone;
 *  - loading's spinner stops under `prefers-reduced-motion`.
 * Wording stays with each caller (or `src/state/errorCopy.ts`) -- only the look and semantics are shared.
 */
export function StatusMessage({ kind, children, title, action, block = false }: StatusMessageProps) {
  const { role, assertive } = STATE_VOCABULARY[kind];
  const Icon = ICONS[kind];
  const isAlertStyle = role === "alert";

  const layout = isAlertStyle
    ? `${ALERT_STYLE} flex items-start gap-1.5`
    : block
      ? "flex flex-col items-center gap-2 text-center py-8 text-xs text-muted-foreground"
      : "flex items-start gap-1.5 text-xs text-muted-foreground";

  const iconClass = [
    block && !isAlertStyle ? "h-6 w-6" : "h-3.5 w-3.5 mt-px",
    "shrink-0",
    kind === "loading" ? "animate-spin motion-reduce:animate-none" : "",
  ].join(" ");

  return (
    <div
      role={role ?? undefined}
      aria-live={assertive ? "assertive" : undefined}
      data-state={kind}
      className={layout}
    >
      <Icon className={iconClass} aria-hidden="true" data-state-icon={kind} />
      <div className="space-y-1.5">
        {title && <div className="font-medium">{title}</div>}
        <div>{children}</div>
        {action && (
          <button
            type="button"
            onClick={action.onClick}
            className="text-[11px] underline underline-offset-2 hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-sm"
          >
            {action.label}
          </button>
        )}
      </div>
    </div>
  );
}
