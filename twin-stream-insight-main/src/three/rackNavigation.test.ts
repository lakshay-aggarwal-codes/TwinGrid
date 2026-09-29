import { describe, it, expect } from "vitest";
import { describeRack, isNavKey, nextRackId } from "./rackNavigation.ts";

describe("rackNavigation", () => {
  it("lands on the first rack when nothing is selected", () => {
    expect(nextRackId(null, "ArrowRight")).toBe("zone-1-row-1-rack-1");
    expect(nextRackId(null, "ArrowDown")).toBe("zone-1-row-1-rack-1");
  });

  it("moves along a row and stops at the edge of the facility", () => {
    expect(nextRackId("zone-1-row-1-rack-1", "ArrowRight")).toBe("zone-1-row-1-rack-2");
    expect(nextRackId("zone-1-row-1-rack-2", "ArrowLeft")).toBe("zone-1-row-1-rack-1");
    expect(nextRackId("zone-1-row-1-rack-1", "ArrowLeft")).toBe("zone-1-row-1-rack-1");
    expect(nextRackId("zone-3-row-1-rack-6", "ArrowRight")).toBe("zone-3-row-1-rack-6");
  });

  it("continues into the next zone at the end of a row", () => {
    expect(nextRackId("zone-1-row-1-rack-6", "ArrowRight")).toBe("zone-2-row-1-rack-1");
    expect(nextRackId("zone-2-row-2-rack-1", "ArrowLeft")).toBe("zone-1-row-2-rack-6");
  });

  it("moves between the two rows of a zone at the same position", () => {
    expect(nextRackId("zone-2-row-1-rack-3", "ArrowDown")).toBe("zone-2-row-2-rack-3");
    expect(nextRackId("zone-2-row-2-rack-3", "ArrowUp")).toBe("zone-2-row-1-rack-3");
    expect(nextRackId("zone-2-row-1-rack-3", "ArrowUp")).toBe("zone-2-row-1-rack-3");
    expect(nextRackId("zone-2-row-2-rack-3", "ArrowDown")).toBe("zone-2-row-2-rack-3");
  });

  it("jumps to the first/last rack with Home/End", () => {
    expect(nextRackId("zone-2-row-1-rack-3", "Home")).toBe("zone-1-row-1-rack-1");
    expect(nextRackId("zone-2-row-1-rack-3", "End")).toBe("zone-3-row-2-rack-6");
  });

  it("describes racks for screen readers", () => {
    expect(describeRack("zone-1-row-2-rack-3")).toBe("Zone A, row 2, rack 3");
    expect(describeRack("nope")).toBe("nope");
  });

  it("recognises only navigation keys", () => {
    expect(isNavKey("ArrowUp")).toBe(true);
    expect(isNavKey("Enter")).toBe(false);
  });
});
