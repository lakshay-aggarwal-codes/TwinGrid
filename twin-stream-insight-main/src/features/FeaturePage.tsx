import type { ReactNode } from "react";
import NotFound from "@/pages/NotFound";
import { useRole } from "@/hooks/useAuth.ts";
import type { FeatureRoute } from "./registry";
import { roleAllows } from "./roles";
import type { FeatureRole } from "./types";

/** UX gate only (the backend enforces roles). A role that may not use the page gets the ordinary 404 page. */
function RoleGate({ minRole, children }: { minRole?: FeatureRole; children: ReactNode }) {
  const { role } = useRole();
  return roleAllows(role, minRole) ? <>{children}</> : <NotFound />;
}

/** One feature route's element: the feature's (usually lazy) page behind the role gate. */
export function FeaturePage({ route }: { route: FeatureRoute }) {
  const Page = route.component;
  return (
    <RoleGate minRole={route.minRole}>
      <Page />
    </RoleGate>
  );
}
