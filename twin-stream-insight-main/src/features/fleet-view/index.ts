import { Network } from "lucide-react";
import { lazy } from "react";
import type { FeatureModule } from "../types";

const FleetPage = lazy(() => import("./FleetPage"));

/** Task 30: the fleet view (`/fleet`): five SIMULATED sites ranked by PUE, carbon and simulated alert conditions, with a drill-down. Reads `GET /api/fleet/sites` only. */
const feature: FeatureModule = {
  id: "fleet-view",
  route: { path: "/fleet", component: FleetPage },
  nav: { label: "Fleet view", icon: Network, group: "Explore", order: 50, minRole: "viewer" },
};
export default feature;
