import { Wrench } from "lucide-react";
import { lazy } from "react";
import type { FeatureModule } from "../types";

const MaintenancePage = lazy(() => import("./MaintenancePage"));

/**
 * Task 28: predictive maintenance and work orders. `/maintenance` shows per-asset health and the degradation trend from
 * `GET /api/maintenance/health` (a rule on simulated data; no remaining-life figure, the backend says why), the existing
 * equipment-health model's methodology metrics, and work orders (`/api/maintenance/work-orders`): create by hand, from an
 * alert or from a health warning (operator), then follow the status flow. A work order is a record only.
 */
const feature: FeatureModule = {
  id: "maintenance",
  route: { path: "/maintenance", component: MaintenancePage },
  nav: { label: "Maintenance", icon: Wrench, group: "Operate", order: 30, minRole: "viewer" },
};
export default feature;
