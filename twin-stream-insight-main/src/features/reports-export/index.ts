import { FileText } from "lucide-react";
import { lazy } from "react";
import type { FeatureModule } from "../types";

const ReportPage = lazy(() => import("./ReportPage"));

/**
 * Task 22: printable executive / ESG report (`/report`) plus the shared export + share-link components other pages import
 * (`ExportButtons`, `ShareLinkButton`, `exportTable`). The command palette lists the page through its nav entry.
 */
const feature: FeatureModule = {
  id: "reports-export",
  route: { path: "/report", component: ReportPage },
  nav: { label: "Report", icon: FileText, group: "Explore", order: 30, minRole: "viewer" },
};
export default feature;
