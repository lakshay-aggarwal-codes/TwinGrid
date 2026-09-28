import type { ReactNode } from "react";
import { Loader2, Inbox } from "lucide-react";

interface StatusMessageProps {
  kind: "loading" | "error" | "empty";
  children: ReactNode;
  /** Optional recovery action (e.g. Retry / Dismiss) -- error only. */
  action?: { label: string; onClick: () => void };
  /** Centered block for whole-panel states (e.g. a list that has no content
   * yet); omit for inline states that sit inside an existing section. */
  block?: boolean;
}

/**
 * Stage 14: the one visual pattern for every loading / error / empty state
 * in the app. Before this, the same three situations were drawn four
 * different ways (bare muted text, spinner + text, bare red text, and a
 * bordered alert box). Now:
 *  - loading: spinner + muted text (role="status")
 *  - error:   bordered destructive box (role="alert"), optional action
 *  - empty:   muted icon + text
 * Wording stays with each caller -- only the look and semantics are shared.
 */
export function StatusMessage({ kind, children, action, block = false }: StatusMessageProps) {
  if (kind === "error") {
    return (
      <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 p-2.5 text-xs text-destructive space-y-1.5">
        <div>{children}</div>
        {action && (
          <button
            onClick={action.onClick}
            className="text-[11px] underline underline-offset-2 hover:text-foreground transition-colors"
          >
            {action.label}
          </button>
        )}
      </div>
    );
  }

  const layout = block ? "flex flex-col items-center gap-2 text-center py-8" : "flex items-center gap-1.5";

  return (
    <div role="status" className={`${layout} text-xs text-muted-foreground`}>
      {kind === "loading" ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
      ) : (
        <Inbox className={block ? "h-6 w-6" : "h-3.5 w-3.5 shrink-0"} />
      )}
      <span>{children}</span>
    </div>
  );
}
