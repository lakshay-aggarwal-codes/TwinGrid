import { History } from "lucide-react";
import { lazy } from "react";
import type { FeatureModule } from "../types";

const ReplayPage = lazy(() => import("./ReplayPage"));

/**
 * Task 14: replay and time travel over stored telemetry (`/replay`). The page owns the replay state; the command palette
 * lists it automatically through its nav entry ("Go to Replay").
 */
const feature: FeatureModule = {
  id: "replay",
  route: { path: "/replay", component: ReplayPage },
  nav: { label: "Replay", icon: History, group: "Explore", order: 10, minRole: "viewer" },
};
export default feature;
