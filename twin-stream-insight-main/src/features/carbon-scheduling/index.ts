import { lazy } from "react";
import type { FeatureModule } from "../types";

const CarbonScheduleCard = lazy(() => import("./CarbonScheduleCard"));

/**
 * Task 27: carbon-aware scheduling suggestions (`GET /api/carbon/schedule`) as a dashboard card. Read-only. With the
 * flat fallback carbon signal it says "No carbon variation in current data" and claims no saving; an explicitly
 * labelled synthetic profile can be shown for demonstration. No route, no nav entry.
 */
const feature: FeatureModule = {
  id: "carbon-scheduling",
  slots: [{ slot: "dashboard", component: CarbonScheduleCard, order: 60 }],
};
export default feature;
