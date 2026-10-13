import type { ReactElement } from "react";
import { Route } from "react-router-dom";
import { FeaturePage } from "./FeaturePage";
import { featureRegistry, type FeatureRegistry } from "./registry";

/** Place `{featureRouteElements()}` inside `<Routes>`, above the catch-all. A Fragment of <Route>s, which Routes accepts. */
export function featureRouteElements(registry: FeatureRegistry = featureRegistry): ReactElement {
  return (
    <>
      {registry.allRoutes().map((r) => (
        <Route key={r.path} path={r.path} element={<FeaturePage route={r} />} />
      ))}
    </>
  );
}
