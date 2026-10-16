import { Boxes } from "lucide-react";
import { lazy } from "react";
import type { FeatureModule } from "../types";
import OverlayControl from "./OverlayControl";

const CapacityPage = lazy(() => import("./CapacityPage"));

/**
 * Task 26: capacity planner. `/capacity` shows facility headroom and the "add N racks at X kW" what-if
 * (`GET /api/capacity/headroom`); the `facility-inspector` slot adds the headroom overlay switch for the 3D view.
 * Model-based estimate on simulated data.
 */
const feature: FeatureModule = {
  id: "capacity",
  route: { path: "/capacity", component: CapacityPage },
  nav: { label: "Capacity", icon: Boxes, group: "Explore", order: 40, minRole: "viewer" },
  slots: [{ slot: "facility-inspector", component: OverlayControl, order: 15 }],
};
export default feature;
