import { describe, expect, it } from "vitest";
import type { Asset } from "@/contract/schemas/facility";
import { EXPECTED_RACK_COUNT, FALLBACK_LAYOUT } from "./facilityLayout";
import { buildFacilityModel, RACK_BOX_M, SCENE_UNITS_PER_FRAME_UNIT, type FacilityModel } from "./facilityModel";
import { FRAME_NOTE, seedAssets, topologyInput } from "./facilityFixtures";

function ok(input = topologyInput()): FacilityModel {
  const r = buildFacilityModel(input);
  if (r.ok === false) throw new Error(`rejected: ${r.reason} ${r.detail ?? ""}`);
  return r.model;
}

describe("buildFacilityModel with the seeded backend topology", () => {
  it("rack ids are the backend external_ids and match the built-in layout exactly (UQ-2 parity)", () => {
    const m = ok();
    expect(m.racks).toHaveLength(EXPECTED_RACK_COUNT);
    expect(m.racks.map((r) => r.rackId)).toEqual(FALLBACK_LAYOUT.racks.map((r) => r.rackId));
    expect(m.zones.map((z) => z.zoneId)).toEqual(FALLBACK_LAYOUT.zones.map((z) => z.zoneId));
    expect(m.zones.map((z) => z.label)).toEqual(["Zone A", "Zone B", "Zone C"]);
  });

  it("positions come from the backend poses through the single unit conversion (1 m = 1 scene unit)", () => {
    const m = ok();
    expect(SCENE_UNITS_PER_FRAME_UNIT.m).toBe(1);
    for (const [i, r] of m.racks.entries()) {
      const want = FALLBACK_LAYOUT.racks[i].position;
      r.position.forEach((v, k) => expect(v).toBeCloseTo(want[k], 9));
    }
  });

  it("a different backend scale moves the racks: nothing is hidden or re-scaled client-side", () => {
    const a = ok(topologyInput({ scale: 1 }));
    const b = ok(topologyInput({ scale: 2 }));
    expect(b.racks[7].position[0]).toBeCloseTo(a.racks[7].position[0] * 2, 9);
    expect(b.racks[7].position[1]).toBeCloseTo(a.racks[7].position[1] * 2, 9);
    // The drawn box is a fixed representative size, not derived from the scale.
    expect(b.racks[7].size).toEqual([...RACK_BOX_M]);
  });

  it("carries the backend identity: asset id, external id, name, type, zone, pose with unit data and valid_from", () => {
    const r = ok().racks[0];
    expect(r).toMatchObject({ rackId: "zone-1-row-1-rack-1", externalId: "zone-1-row-1-rack-1", assetType: "rack", zoneExternalId: "zone-1", zoneId: "zone-1", rowId: "row-1" });
    expect(r.assetId).toBeGreaterThan(0);
    expect(r.pose).toEqual({ x: r.position[0], y: r.position[1], z: r.position[2], rotationDeg: 0, validFrom: "2026-10-02T00:00:00Z" });
  });

  it("exposes the frame unit and the backend's own frame note, unmodified", () => {
    const m = ok();
    expect(m.frameUnit).toBe("m");
    expect(m.frameNote).toBe(FRAME_NOTE);
    expect(m.unplaced).toEqual([]);
  });

  it("zone outlines are derived from the backend rack poses and equal the built-in outlines for the seeded layout", () => {
    const m = ok();
    for (const [i, z] of m.zones.entries()) {
      const want = FALLBACK_LAYOUT.zones[i].bounds;
      expect(z.bounds.centerX).toBeCloseTo(want.centerX, 9);
      expect(z.bounds.centerZ).toBeCloseTo(want.centerZ, 9);
      expect(z.bounds.width).toBeCloseTo(want.width, 9);
      expect(z.bounds.depth).toBeCloseTo(want.depth, 9);
    }
  });

  it("order is deterministic from the poses, whatever order the backend sends", () => {
    const shuffled = [...seedAssets()].reverse();
    expect(ok(topologyInput({ assets: shuffled })).racks.map((r) => r.rackId)).toEqual(FALLBACK_LAYOUT.racks.map((r) => r.rackId));
  });
});

describe("what the adapter excludes or refuses", () => {
  const without = (id: string, patch: Partial<Asset>) => seedAssets().map((a) => (a.external_id === id ? { ...a, ...patch } : a));

  it("an asset with a null pose is excluded and listed as unplaced (here: 35 placed -> count mismatch is reported, not hidden)", () => {
    const r = buildFacilityModel(topologyInput({ assets: without("zone-1-row-1-rack-1", { pose: null }) }));
    expect(r).toMatchObject({ ok: false, reason: "count_mismatch" });
  });

  it("with an extra unplaced rack on top of the 36, the placed 36 render and the extra is listed as unplaced (no pose)", () => {
    const extra: Asset = { id: 999, external_id: "rack-spare", name: "spare", asset_type: "rack", retired_at: null, pose: null, located_in: null };
    const m = ok(topologyInput({ assets: [...seedAssets(), extra] }));
    expect(m.racks.map((r) => r.rackId)).not.toContain("rack-spare");
    expect(m.unplaced).toEqual([{ assetId: 999, externalId: "rack-spare", assetType: "rack", reason: "no_pose" }]);
  });

  it("a rack with a pose but no placed zone is unplaced (no zone), not drawn at an invented place", () => {
    const stray: Asset = {
      id: 1000,
      external_id: "rack-stray",
      name: "stray",
      asset_type: "rack",
      retired_at: null,
      pose: { x: 50, y: 1, z: 50, rotation_deg: 0, valid_from: "2026-10-02T00:00:00Z", valid_to: null },
      located_in: null,
    };
    const m = ok(topologyInput({ assets: [...seedAssets(), stray] }));
    expect(m.unplaced).toEqual([{ assetId: 1000, externalId: "rack-stray", assetType: "rack", reason: "no_zone" }]);
    expect(m.racks).toHaveLength(36);
  });

  it("retired assets are skipped (they are not unplaced, they are gone)", () => {
    const m = ok(topologyInput({ assets: [...seedAssets(), { id: 5000, external_id: "old", name: "old", asset_type: "rack", retired_at: "2026-01-01T00:00:00Z", pose: null, located_in: null }] }));
    expect(m.unplaced).toEqual([]);
  });

  it("other asset types (e.g. facility-level) are ignored, not drawn", () => {
    const m = ok(topologyInput({ assets: [...seedAssets(), { id: 7000, external_id: "facility-level", name: "agg", asset_type: "facility", retired_at: null, pose: null, located_in: null }] }));
    expect(m.racks).toHaveLength(36);
    expect(m.unplaced).toEqual([]);
  });

  it("a rack count other than 36 is refused, with the numbers stated; ids are never remapped", () => {
    const r = buildFacilityModel(topologyInput({ assets: seedAssets().filter((a) => a.external_id !== "zone-3-row-2-rack-6") }));
    expect(r).toEqual({ ok: false, reason: "count_mismatch", detail: "35 placed racks, expected 36" });
  });

  it("no placed racks -> empty", () => {
    expect(buildFacilityModel(topologyInput({ assets: [] }))).toMatchObject({ ok: false, reason: "empty" });
    expect(buildFacilityModel(topologyInput({ assets: seedAssets().filter((a) => a.asset_type !== "rack") }))).toMatchObject({ ok: false, reason: "empty" });
  });

  it.each(["ft", "scene", "", "M"])("an unsupported frame unit %j is refused, never guessed", (unit) => {
    const r = buildFacilityModel(topologyInput({ facility: { frame_unit: unit, frame_note: "x" }, assetsFrameUnit: unit }));
    expect(r).toMatchObject({ ok: false, reason: "unsupported_frame_unit" });
  });

  it("disagreeing frame units between /api/facility and /api/assets are invalid", () => {
    expect(buildFacilityModel(topologyInput({ assetsFrameUnit: "ft" }))).toMatchObject({ ok: false, reason: "invalid" });
  });

  it("duplicate external ids are invalid", () => {
    const dup = [...seedAssets(), { ...seedAssets()[5], id: 8000 }];
    expect(buildFacilityModel(topologyInput({ assets: dup }))).toMatchObject({ ok: false, reason: "invalid" });
  });

  it("a rack id that does not follow the zone-row-rack pattern still works (row label simply absent)", () => {
    const renamed = seedAssets().map((a) => (a.external_id === "zone-1-row-1-rack-1" ? { ...a, external_id: "R-0001" } : a));
    const m = ok(topologyInput({ assets: renamed }));
    const r = m.racks.find((x) => x.rackId === "R-0001")!;
    expect(r.rowId).toBe("");
    expect(r.zoneId).toBe("zone-1");
  });
});
