import { describe, expect, it } from "vitest";
import { createFeatureRegistry } from "../registry";
import feature from "./index";

describe("carbon-scheduling registration", () => {
  it("is accepted by the registry as one dashboard widget, with no route and no nav entry", () => {
    const r = createFeatureRegistry([feature], { onReject: () => undefined });
    expect(r.rejected).toEqual([]);
    expect(r.allRoutes()).toEqual([]);
    expect(r.navGroups("viewer")).toEqual([]);
    expect(r.slotWidgets("dashboard", "viewer")).toHaveLength(1);
  });
});
