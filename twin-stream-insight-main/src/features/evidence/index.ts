import { ShieldCheck } from "lucide-react";
import { lazy } from "react";
import type { FeatureModule } from "../types";

const EvidencePage = lazy(() => import("./EvidencePage"));

/**
 * Task 26: the Evidence page (`/evidence`). Static: the claims ledger, model status, architecture, how the build was
 * verified and a skills map, all generated from the repository's own documents by `scripts/build_evidence.py`.
 * Makes no API call, so it works for the read-only demo session and without the backend.
 */
const feature: FeatureModule = {
  id: "evidence",
  route: { path: "/evidence", component: EvidencePage },
  nav: { label: "Evidence", icon: ShieldCheck, group: "Evidence", order: 10, minRole: "viewer" },
};
export default feature;
