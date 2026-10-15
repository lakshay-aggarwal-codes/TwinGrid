import type { FeatureModule } from "../types";
import DashboardModels from "./DashboardModels";
import PassportHost from "./PassportHost";
import { openPassport } from "./passportStore";


/**
 * Task 18: explainability and the Model Passport. A header button + one global drawer (every model-driven widget opens
 * it), a dashboard card, a command, and the "Why did this fire?" disclosure that AlertDetail renders. Read-only:
 * `GET /api/models/passport`, `GET /api/alerts/{id}/explanation`. No route and no nav entry.
 */
const feature: FeatureModule = {
  id: "explainability",
  slots: [
    { slot: "header-actions", component: PassportHost, order: 30 },
    { slot: "dashboard", component: DashboardModels, order: 40 },
  ],
  commands: [
    { id: "explainability.open-passport", label: "Open the Model Passport", group: "Explore", keywords: ["model", "card", "passport", "limitations", "synthetic"], run: () => openPassport() },
  ],
};
export default feature;
