import { lazy } from "react";
import type { FeatureModule } from "../types";

const EconomicsCard = lazy(() => import("./EconomicsCard"));

/**
 * Task 25: energy cost under an illustrative tariff (`GET /api/economics/summary`) as a dashboard card with a tariff
 * settings drawer. Read-only on the backend; the tariff is kept in this browser. No route, no nav entry.
 */
const feature: FeatureModule = {
  id: "economics",
  slots: [{ slot: "dashboard", component: EconomicsCard, order: 50 }],
};
export default feature;
