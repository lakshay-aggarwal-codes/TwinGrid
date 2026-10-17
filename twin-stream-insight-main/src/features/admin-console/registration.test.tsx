import { describe, expect, it } from "vitest";
import { createFeatureRegistry } from "../registry";
import feature from "./index";

describe("admin-console registration (permission: no nav item for a non-admin)", () => {
  const r = createFeatureRegistry([feature], { onReject: () => undefined });

  it("is accepted: one route /admin and one nav entry in the Admin group", () => {
    expect(r.rejected).toEqual([]);
    expect(r.allRoutes().map((x) => x.path)).toEqual(["/admin"]);
    expect(r.navGroups("admin")).toMatchObject([{ group: "Admin", items: [{ label: "Admin", path: "/admin" }] }]);
  });

  it.each(["viewer", "operator", "root", "", "Admin", "ADMIN"])("has no nav item for the role %j", (role) => {
    expect(r.navGroups(role)).toEqual([]);
  });

  it("has no nav item when signed out or the role is missing", () => {
    expect(r.navGroups(null as unknown as string)).toEqual([]);
    expect(r.navGroups(undefined as unknown as string)).toEqual([]);
  });
});
