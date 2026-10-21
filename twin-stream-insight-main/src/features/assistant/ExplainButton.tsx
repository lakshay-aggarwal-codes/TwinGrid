import { MessageCircleQuestion } from "lucide-react";
import { openAssistant } from "./store";
import type { ContextRef } from "./schema";

interface Props {
  context: ContextRef;
  label?: string;
  className?: string;
}

/** "Explain this": opens the global assistant drawer for one alert, signal or model. It only sets open state; the answer comes from the server. */
export function ExplainButton({ context, label = "Explain this", className }: Props) {
  return (
    <button
      type="button"
      data-testid="explain-button"
      data-kind={context.kind}
      aria-haspopup="dialog"
      onClick={() => openAssistant(context)}
      className={
        className ??
        "inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-[11px] font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      }
    >
      <MessageCircleQuestion aria-hidden="true" className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}
