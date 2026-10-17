import { ShieldCheck } from "lucide-react";
import { lazy } from "react";
import type { FeatureModule } from "../types";

const AdminPage = lazy(() => import("./AdminPage"));

/**
 * Task 29: the admin console (`/admin`): users and roles, the audit log with filters and export, webhook management with a
 * delivery log, and system status with a link to the API docs. The nav item needs the `admin` role (a UX gate: it is hidden
 * from everyone else; the backend answers 403 to a non-admin on every `/api/admin/*` route).
 */
const feature: FeatureModule = {
  id: "admin-console",
  route: { path: "/admin", component: AdminPage },
  nav: { label: "Admin", icon: ShieldCheck, group: "Admin", order: 10, minRole: "admin" },
};
export default feature;
