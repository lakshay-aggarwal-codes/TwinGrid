import { lazy } from "react";
import type { FeatureModule } from "../types";

const KpiCards = lazy(() => import("./KpiCards"));
const GoalRings = lazy(() => import("./GoalRings"));
const InsightsFeed = lazy(() => import("./InsightsFeed"));

/**
 * Task 16: executive dashboard widgets in the `dashboard` slot (the Analytics page): KPI cards with animated counters
 * and sparklines, goal rings with targets kept in this browser, and a rule-based Insights feed. Reads
 * `GET /api/whatif`, `GET /api/evaluations`, `GET /api/alerts` and the live feed; writes nothing to the backend.
 */
const feature: FeatureModule = {
  id: "executive-dashboard",
  slots: [
    { slot: "dashboard", component: KpiCards, order: 10 },
    { slot: "dashboard", component: GoalRings, order: 20 },
    { slot: "dashboard", component: InsightsFeed, order: 30 },
  ],
};
export default feature;
