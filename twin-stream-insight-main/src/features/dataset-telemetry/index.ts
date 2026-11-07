import { Database } from "lucide-react";
import { lazy } from "react";
import type { FeatureModule } from "../types";

const DatasetTelemetryPage = lazy(() => import("./DatasetTelemetryPage"));

/**
 * Task 17: individual rack readouts from an imported dataset (`/dataset-telemetry`). Operator-gated in the UI to match the
 * Task 9 decision that demo tokens are refused for dataset routes (the backend enforces it; this is only a UX gate).
 */
const feature: FeatureModule = {
  id: "dataset-telemetry",
  route: { path: "/dataset-telemetry", component: DatasetTelemetryPage },
  nav: { label: "Dataset telemetry", icon: Database, group: "Explore", order: 90, minRole: "operator" },
};
export default feature;
