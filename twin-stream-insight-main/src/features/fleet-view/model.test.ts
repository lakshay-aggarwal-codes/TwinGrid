import { afterEach, describe, expect, it, vi } from "vitest";
import { FLEET } from "./testFixtures";
import { getSite, labLink, setSite, siteFromSearch, sortSites, withSite } from "./model";

afterEach(() => setSite(null));
const ids = (key: Parameters<typeof sortSites>[1]) => sortSites(FLEET.sites, key).map((s) => s.id);

describe("sorting", () => {
  it("orders best first by each key and keeps the backend's overall order for ties", () => {
    expect(ids("overall")).toEqual(["sim-a", "sim-d", "sim-c", "sim-e", "sim-b"]);
    expect(ids("pue")).toEqual(["sim-a", "sim-d", "sim-c", "sim-b", "sim-e"]);
    expect(ids("carbon")).toEqual(["sim-b", "sim-a", "sim-c", "sim-d", "sim-e"]);
    expect(ids("alerts")).toEqual(["sim-a", "sim-d", "sim-c", "sim-e", "sim-b"]); // four tied at 1: overall order decides
  });
  it("does not mutate its input", () => {
    const before = FLEET.sites.map((s) => s.id);
    sortSites(FLEET.sites, "pue");
    expect(FLEET.sites.map((s) => s.id)).toEqual(before);
  });
});

describe("site context and address", () => {
  it("only accepts a site the backend listed", () => {
    expect(siteFromSearch("?site=sim-c", ["sim-a", "sim-c"])).toBe("sim-c");
    expect(siteFromSearch("?site=nope", ["sim-a"])).toBeNull();
    expect(siteFromSearch("", ["sim-a"])).toBeNull();
  });
  it("writes and clears the site parameter and keeps the others", () => {
    expect(withSite("?x=1", "sim-b")).toBe("?x=1&site=sim-b");
    expect(withSite("?x=1&site=sim-b", null)).toBe("?x=1");
    expect(withSite("", null)).toBe("");
  });
  it("switching the site context notifies subscribers once per change", () => {
    const seen = vi.fn();
    expect(getSite()).toBeNull();
    setSite("sim-a");
    seen(getSite());
    setSite("sim-a"); // no change
    setSite("sim-d");
    seen(getSite());
    expect(seen.mock.calls).toEqual([["sim-a"], ["sim-d"]]);
  });
});

describe("lab link", () => {
  it("carries the site's load percent and ambient temperature", () => {
    expect(labLink(FLEET.sites[0])).toBe("/whatif-lab?load=55&amb=15&mode=auto");
  });
});
