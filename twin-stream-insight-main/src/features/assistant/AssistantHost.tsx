import { useMemo, useSyncExternalStore } from "react";
import { MessageCircleQuestion } from "lucide-react";
import { CORE_ROUTE_PATHS, featureRegistry } from "../registry";
import { AssistantDrawer } from "./AssistantDrawer";
import { closeAssistant, getAssistantState, openAssistant, subscribeAssistant } from "./store";

/** Slot `header-actions`: the one "Ask" button and the one drawer every "Explain this" button opens. */
export default function AssistantHost() {
  const s = useSyncExternalStore(subscribeAssistant, getAssistantState, getAssistantState);
  const knownRoutes = useMemo(() => [...CORE_ROUTE_PATHS, ...featureRegistry.allRoutes().map((r) => r.path)], []);
  return (
    <>
      <button
        type="button"
        data-testid="assistant-open"
        aria-haspopup="dialog"
        onClick={() => openAssistant()}
        className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-[11px] font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <MessageCircleQuestion aria-hidden="true" className="h-3.5 w-3.5" />
        Ask
      </button>
      <AssistantDrawer open={s.open} context={s.context} nonce={s.nonce} onClose={closeAssistant} knownRoutes={knownRoutes} />
    </>
  );
}
