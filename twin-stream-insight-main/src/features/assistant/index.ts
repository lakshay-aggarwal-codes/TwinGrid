import type { FeatureModule } from "../types";
import AssistantHost from "./AssistantHost";
import { openAssistant } from "./store";

/**
 * Task 15: the Copilot drawer and "Explain this". One header button + one global drawer; every "Explain this" button
 * opens it for an alert, a signal or a model. Read-only: `POST /api/copilot/ask`. No route, no nav entry.
 * The answers are rule-based unless the server says otherwise; the drawer shows which.
 */
const feature: FeatureModule = {
  id: "assistant",
  slots: [{ slot: "header-actions", component: AssistantHost, order: 35 }],
  commands: [{ id: "assistant.open", label: "Ask the assistant", group: "Explore", keywords: ["ask", "explain", "why", "copilot", "help"], run: () => openAssistant() }],
};
export default feature;
