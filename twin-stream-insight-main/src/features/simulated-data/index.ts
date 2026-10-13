import type { FeatureModule } from "../types";
import HeaderSimulatedBadge from "./SimulatedDataBadge";

/** Task 5: a "Simulated data" badge in the header, driven by the live feed's `origin` field. No route, no nav. */
const feature: FeatureModule = {
  id: "simulated-data",
  slots: [{ slot: "header-actions", component: HeaderSimulatedBadge, order: 10 }],
};
export default feature;
