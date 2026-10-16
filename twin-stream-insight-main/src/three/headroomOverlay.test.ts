import { afterEach, describe, expect, it, vi } from "vitest";
import { STATUS_STYLE, evenShare, headroomOverlay, zoneLabel } from "./headroomOverlay";

afterEach(() => headroomOverlay.reset());

describe("evenShare", () => {
  it("splits a facility total equally, and says nothing without a total or a zone", () => {
    expect(evenShare(105, 3)).toBe(35);
    expect(evenShare(-60, 3)).toBe(-20);
    expect(evenShare(null, 3)).toBeNull();
    expect(evenShare(105, 0)).toBeNull();
    expect(evenShare(Number.NaN, 3)).toBeNull();
  });
});

describe("zoneLabel", () => {
  const on = { enabled: true, status: "tight", powerKw: 75, coolingKw: 150 } as const;
  it("carries a glyph and a word as well as the colour, and says the share is even", () => {
    expect(zoneLabel(on, 3)).toBe("▲ tight · even share: power 25 kW, cooling 50 kW");
    expect(zoneLabel({ ...on, status: "exceeded", powerKw: -30, coolingKw: null }, 3)).toBe("■ exceeded · even share: power -10 kW, cooling n/a");
    expect(zoneLabel({ ...on, status: "ok" }, 3)?.startsWith("● ok")).toBe(true);
  });
  it("is null while off or without a result", () => {
    expect(zoneLabel({ ...on, enabled: false }, 3)).toBeNull();
    expect(zoneLabel({ ...on, status: null }, 3)).toBeNull();
  });
  it("gives each status a distinct glyph and colour", () => {
    const s = Object.values(STATUS_STYLE);
    expect(new Set(s.map((x) => x.glyph)).size).toBe(3);
    expect(new Set(s.map((x) => x.color)).size).toBe(3);
  });
});

describe("headroomOverlay store", () => {
  it("starts off, publishes patches, notifies once per real change and resets", () => {
    const l = vi.fn();
    const off = headroomOverlay.subscribe(l);
    expect(headroomOverlay.getState()).toEqual({ enabled: false, status: null, powerKw: null, coolingKw: null });
    headroomOverlay.publish({ enabled: true });
    headroomOverlay.publish({ enabled: true }); // no change: no notification
    expect(l).toHaveBeenCalledTimes(1);
    headroomOverlay.publish({ status: "ok", powerKw: 10, coolingKw: 20 });
    expect(headroomOverlay.getState()).toEqual({ enabled: true, status: "ok", powerKw: 10, coolingKw: 20 });
    headroomOverlay.reset();
    expect(headroomOverlay.getState().enabled).toBe(false);
    off();
    headroomOverlay.publish({ enabled: true });
    expect(l).toHaveBeenCalledTimes(3); // unsubscribed: no further calls
  });
});
