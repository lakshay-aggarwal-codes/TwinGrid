import { BellRing } from "lucide-react";
import { lazy } from "react";
import type { FeatureModule } from "../types";
import AlertWatcher from "./AlertWatcher";

const AlertsPage = lazy(() => import("./AlertsPage"));

/**
 * Task 17: the alerts centre (`/alerts`): inbox with severity/status filters, bulk acknowledge, assignee and notes,
 * incident timeline, and an app-wide notifier in the header (toast + live region + optional sound for new critical
 * alerts). Reads `GET /api/alerts/inbox` and `/api/alerts/{id}/events`; writes only `PATCH /api/alerts/{id}` (operator).
 */
const feature: FeatureModule = {
  id: "alerts-centre",
  route: { path: "/alerts", component: AlertsPage },
  nav: { label: "Alerts centre", icon: BellRing, group: "Operate", order: 10, minRole: "viewer" },
  slots: [{ slot: "header-actions", component: AlertWatcher, order: 20 }],
};
export default feature;
