import { Gauge } from "lucide-react";
import { lazy } from "react";
import type { FeatureModule } from "../types";

const OptimizerPage = lazy(() => import("./OptimizerPage"));

/**
 * Task 19: `/optimizer`. PPO status and run (a 503 is shown with its reason), the best baseline controller's recommendation
 * with a sandbox, operator proposals that a different admin approves or rejects (audit-logged), and the shadow-mode comparison.
 */
const feature: FeatureModule = {
  id: "optimizer-approvals",
  route: { path: "/optimizer", component: OptimizerPage },
  nav: { label: "Optimizer", icon: Gauge, group: "Operate", order: 20, minRole: "viewer" },
};
export default feature;
