/**
 * FE-14 test support. Test-only; never import from app code.
 *
 * `seedAssets(scale)` is a hand-built mirror of what `scripts/seed_facility.py` writes (3 zones, 36 racks, external_id =
 * the layout rack id, poses = scene position x scale, `located_in` -> zone), in the exact /api/assets response shape.
 * It is NOT a captured backend response (the contract fixtures folder holds none yet); parity with the real seed is
 * additionally pinned by the backend's own `tests/test_facility_seed.py`.
 */
import type { Asset } from "@/contract/schemas/facility";
import { FALLBACK_LAYOUT } from "./facilityLayout";
import type { TopologyInput } from "./facilityModel";

const VALID_FROM = "2026-10-02T00:00:00Z";

export function seedAssets(scale = 1): Asset[] {
  let id = 1;
  const zoneId = new Map<string, number>();
  const assets: Asset[] = [];
  for (const z of FALLBACK_LAYOUT.zones) {
    const a: Asset = {
      id: id++,
      external_id: z.zoneId,
      name: z.label,
      asset_type: "zone",
      retired_at: null,
      pose: { x: z.bounds.centerX * scale, y: 0, z: z.bounds.centerZ * scale, rotation_deg: 0, valid_from: VALID_FROM, valid_to: null },
      located_in: null,
    };
    zoneId.set(z.zoneId, a.id);
    assets.push(a);
  }
  for (const r of FALLBACK_LAYOUT.racks) {
    assets.push({
      id: id++,
      external_id: r.rackId,
      name: r.rackId,
      asset_type: "rack",
      retired_at: null,
      pose: { x: r.position[0] * scale, y: r.position[1] * scale, z: r.position[2] * scale, rotation_deg: 0, valid_from: VALID_FROM, valid_to: null },
      located_in: { edge_id: id, parent_asset_id: zoneId.get(r.zoneId)!, parent_external_id: r.zoneId, valid_from: VALID_FROM, valid_to: null },
    });
  }
  return assets;
}

export const FRAME_NOTE = "Unit: metre. Right-handed frame, Y up. Scene-unit -> metre factor: 1.0 m per scene unit.";

export function topologyInput(over: Partial<TopologyInput> & { scale?: number } = {}): TopologyInput {
  return {
    facility: { frame_unit: "m", frame_note: FRAME_NOTE },
    assetsFrameUnit: "m",
    assets: seedAssets(over.scale ?? 1),
    ...over,
  };
}
