import { describe, expect, it, vi } from "vitest";
import appSource from "../App.tsx?raw";
import { Beaker } from "lucide-react";
import example from "@/test/fixtures/exampleFeature";
import { CORE_ROUTE_PATHS, createFeatureRegistry, featureRegistry } from "./registry";
import { createCommandRegistry } from "./commands";
import { roleAllows } from "./roles";
import type { FeatureModule } from "./types";

const C = () => null;
const mod = (over: Partial<FeatureModule> & { id: string }): FeatureModule => ({ ...over });
const quiet = { onReject: () => undefined };

describe("roleAllows", () => {
  it("orders viewer < operator < admin; unknown or missing roles only see unrestricted things", () => {
    expect(roleAllows("viewer")).toBe(true);
    expect(roleAllows(null, undefined)).toBe(true);
    expect(roleAllows("viewer", "operator")).toBe(false);
    expect(roleAllows("operator", "operator")).toBe(true);
    expect(roleAllows("operator", "admin")).toBe(false);
    expect(roleAllows("admin", "viewer")).toBe(true);
    expect(roleAllows("superuser", "viewer")).toBe(false);
    expect(roleAllows(null, "viewer")).toBe(false);
    expect(roleAllows("constructor", "viewer")).toBe(false);
  });
});

describe("feature registration", () => {
  it("registers the example feature: route, nav, commands and slots", () => {
    const r = createFeatureRegistry([example], quiet);
    expect(r.rejected).toEqual([]);
    expect(r.allRoutes().map((x) => x.path)).toEqual(["/example"]);
    expect(r.navGroups("viewer")).toMatchObject([{ group: "Labs", items: [{ label: "Example", path: "/example" }] }]);
    expect(r.allCommands().map((c) => c.id)).toEqual(["example.hello"]);
    expect(r.slotWidgets("dashboard", "viewer")).toHaveLength(1);
    expect(r.slotWidgets("settings", "viewer")).toHaveLength(0);
  });

  it("ships exactly the features listed here (the example lives under src/test)", () => {
    // Task 5 added the first shipped feature. Add an id to this list when a later task ships another one.
    expect(featureRegistry.features.map((f) => f.id)).toEqual([
      "alerts-centre",
      "app-states",
      "capacity",
      "carbon-scheduling",
      "command-palette",
      "design-polish",
      "economics",
      "executive-dashboard",
      "explainability",
      "facility-inspector",
      "fleet-view",
      "guided-tour",
      "maintenance",
      "optimizer-approvals",
      "realtime-resilience",
      "replay",
      "reports-export",
      "simulated-data",
      "what-if-lab",
    ]);
  });

  it("filters nav by role and sorts by group, order, label", () => {
    const nav = (label: string, group: string, order: number, minRole?: "viewer" | "operator" | "admin") => ({ label, group, order, icon: Beaker, minRole });
    const r = createFeatureRegistry(
      [
        mod({ id: "b", route: { path: "/b", component: C }, nav: nav("B", "Ops", 2) }),
        mod({ id: "a", route: { path: "/a", component: C }, nav: nav("A", "Ops", 1) }),
        mod({ id: "c", route: { path: "/c", component: C }, nav: nav("C", "Admin", 1, "operator") }),
        mod({ id: "d", route: { path: "/d", component: C }, nav: nav("D", "Admin", 2, "admin") }),
      ],
      quiet,
    );
    const labels = (role: string) => r.navGroups(role).map((g) => [g.group, g.items.map((i) => i.label)]);
    expect(labels("viewer")).toEqual([["Ops", ["A", "B"]]]);
    expect(labels("operator")).toEqual([["Admin", ["C"]], ["Ops", ["A", "B"]]]);
    expect(labels("admin")).toEqual([["Admin", ["C", "D"]], ["Ops", ["A", "B"]]]);
    expect(labels("mystery")).toEqual([["Ops", ["A", "B"]]]);
  });

  it("orders slot widgets by order and filters them by role", () => {
    const r = createFeatureRegistry(
      [
        mod({ id: "late", slots: [{ slot: "dashboard", component: C, order: 20 }] }),
        mod({ id: "early", slots: [{ slot: "dashboard", component: C, order: 5 }, { slot: "settings", component: C, order: 1 }] }),
        mod({ id: "ops", slots: [{ slot: "dashboard", component: C, order: 10, minRole: "operator" }] }),
      ],
      quiet,
    );
    expect(r.slotWidgets("dashboard", "viewer").map((w) => w.featureId)).toEqual(["early", "late"]);
    expect(r.slotWidgets("dashboard", "operator").map((w) => w.featureId)).toEqual(["early", "ops", "late"]);
    expect(r.slotWidgets("settings", "viewer").map((w) => w.featureId)).toEqual(["early"]);
  });

  it("a route's role defaults to its nav entry's role and can be set explicitly", () => {
    const r = createFeatureRegistry(
      [
        mod({ id: "n", route: { path: "/n", component: C }, nav: { label: "N", icon: Beaker, group: "G", order: 1, minRole: "operator" } }),
        mod({ id: "x", route: { path: "/x", component: C, minRole: "admin" } }),
      ],
      quiet,
    );
    expect(r.allRoutes().map((x) => [x.path, x.minRole])).toEqual([["/n", "operator"], ["/x", "admin"]]);
  });
});

describe("failure isolation: a bad module is rejected alone", () => {
  const good = mod({ id: "good", route: { path: "/good", component: C } });
  const cases: [string, unknown, string][] = [
    ["not an object", 42, "not an object"],
    ["bad id", { id: "Bad Id" }, "id must be"],
    ["core path", mod({ id: "x1", route: { path: "/analytics", component: C } }), "core route"],
    ["under a core path", mod({ id: "x2", route: { path: "/runs/new", component: C } }), "core route"],
    ["root path", mod({ id: "x3", route: { path: "/", component: C } }), "core route"],
    ["wildcard", mod({ id: "x4", route: { path: "/*", component: C } }), "absolute"],
    ["relative path", mod({ id: "x5", route: { path: "rel", component: C } }), "absolute"],
    ["no component", { id: "x6", route: { path: "/x6" } }, "component"],
    ["nav without route", mod({ id: "x7", nav: { label: "L", icon: Beaker, group: "G", order: 1 } }), "nav requires route"],
    ["bad slot name", { id: "x8", slots: [{ slot: "nope", component: C, order: 1 }] }, "slot"],
    ["bad role", mod({ id: "x9", route: { path: "/x9", component: C, minRole: "root" as never } }), "minRole"],
  ];
  it.each(cases)("%s", (_n, bad, reason) => {
    const seen: string[] = [];
    const r = createFeatureRegistry([bad, good], { onReject: (x) => seen.push(x.reason) });
    expect(r.features.map((f) => f.id)).toEqual(["good"]);
    expect(r.rejected).toHaveLength(1);
    expect(r.rejected[0].reason).toContain(reason);
    expect(seen).toHaveLength(1);
  });

  it("rejects duplicate ids and duplicate paths (first wins)", () => {
    const r = createFeatureRegistry(
      [good, mod({ id: "good", slots: [] }), mod({ id: "other", route: { path: "/good/", component: C } })],
      quiet,
    );
    expect(r.features.map((f) => f.id)).toEqual(["good"]);
    expect(r.rejected.map((x) => x.reason)).toEqual(["duplicate feature id", "route.path already used by another feature"]);
  });

  it("warns on the console by default instead of throwing", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    expect(() => createFeatureRegistry([null])).not.toThrow();
    expect(warn).toHaveBeenCalledOnce();
    warn.mockRestore();
  });
});

describe("CORE_ROUTE_PATHS", () => {
  it("covers every path App.tsx declares (so a feature can never shadow a core page)", () => {
    const declared = [...appSource.matchAll(/<Route path="([^"]+)"/g)].map((m) => m[1]).filter((p) => p !== "*");
    expect(declared.length).toBeGreaterThan(3);
    for (const p of declared) {
      const base = p === "/" ? "/" : "/" + p.split("/")[1];
      expect(CORE_ROUTE_PATHS, `App.tsx route ${p}`).toContain(base);
    }
  });
});

describe("command registry", () => {
  it("registers, filters by role, rejects duplicate ids, unregisters, and notifies", () => {
    const rejects: string[] = [];
    const reg = createCommandRegistry((id) => rejects.push(id));
    const listener = vi.fn();
    reg.subscribe(listener);
    const v0 = reg.getVersion();
    const off = reg.register("a", [
      { id: "go", label: "Go", run: () => undefined },
      { id: "ops", label: "Ops", run: () => undefined, minRole: "operator" },
    ]);
    reg.register("b", [{ id: "go", label: "Dup", run: () => undefined }, { id: "", label: "bad", run: () => undefined }]);
    expect(rejects).toEqual(["go", ""]);
    expect(reg.list("viewer").map((c) => c.id)).toEqual(["go"]);
    expect(reg.list("operator").map((c) => c.id)).toEqual(["go", "ops"]);
    expect(reg.get("go")?.label).toBe("Go");
    expect(reg.getVersion()).toBeGreaterThan(v0);
    expect(listener).toHaveBeenCalled();
    off();
    expect(reg.list("operator")).toEqual([]);
  });
});
