import { FlaskConical } from "lucide-react";
import { lazy } from "react";
import type { FeatureModule } from "../types";

const LabPage = lazy(() => import("./LabPage"));

/**
 * Task 15: the what-if lab (`/whatif-lab`): sliders, baseline vs scenario delta cards, a backend sensitivity tornado,
 * saved scenarios, a shareable URL and CSV export. Reads `GET /api/whatif` and `GET /api/whatif/sensitivity` only.
 */
const feature: FeatureModule = {
  id: "what-if-lab",
  route: { path: "/whatif-lab", component: LabPage },
  nav: { label: "What-if lab", icon: FlaskConical, group: "Explore", order: 20, minRole: "viewer" },
};
export default feature;
