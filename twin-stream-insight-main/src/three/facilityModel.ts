/**
 * FE-14: adapter from the backend topology (BC-08) to the scene's `FacilityLayout`. PURE.
 *
 * - `rackId` is the backend `external_id`; `zoneId` is the parent zone's `external_id` (`located_in`). Nothing is remapped.
 * - Backend poses are in `frame_unit` (metres today). The ONE conversion is `SCENE_UNITS_PER_FRAME_UNIT`: for "m" it is 1, i.e. one
 *   scene unit is one metre; an unknown unit is refused rather than guessed. No rotation or offset is applied.
 * - Nothing is generated: no coordinates, zones, sensors or equipment. The only client-side numbers are the representative rack
 *   box (`RACK_BOX_M`, a drawing size -- the backend has no dimensions) and the zone outline padding.
 * - A rack without a pose, or without a placed parent zone, is NOT drawn and is listed as unplaced.
 * - A rack count other than the expected 36 is refused (fallback + badge), not silently accepted.
 */
import type { Asset, Facility } from '@/contract/schemas/facility';
import { EXPECTED_RACK_COUNT, type FacilityLayout, type RackDef, type ZoneDef } from './facilityLayout';

/** The single, documented unit conversion. Add a unit here only with a stated factor. */
export const SCENE_UNITS_PER_FRAME_UNIT: Readonly<Record<string, number>> = { m: 1 };

/** Representative drawing size of a rack in metres (width, height, depth). Not backend data: the backend stores a centre pose only. */
export const RACK_BOX_M: readonly [number, number, number] = [0.6, 2.0, 1.0];
export const ZONE_OUTLINE_PADDING_M = 0.6;

export type UnplacedReason = 'no_pose' | 'no_zone';

export interface UnplacedAsset {
  readonly assetId: number;
  readonly externalId: string;
  readonly assetType: string;
  readonly reason: UnplacedReason;
}

export interface FacilityModel extends FacilityLayout {
  readonly frameUnit: string;
  /** The backend's own description of the coordinate frame (shown as received). */
  readonly frameNote: string;
  readonly unplaced: readonly UnplacedAsset[];
}

export type TopologyRejection = 'empty' | 'count_mismatch' | 'unsupported_frame_unit' | 'invalid';

export type BuildResult =
  | { readonly ok: true; readonly model: FacilityModel }
  | { readonly ok: false; readonly reason: TopologyRejection; readonly detail?: string };

export interface TopologyInput {
  readonly facility: Pick<Facility, 'frame_unit' | 'frame_note'>;
  readonly assetsFrameUnit: string;
  readonly assets: readonly Asset[];
}

const ROW_RE = /(?:^|-)(row-\d+)(?:-|$)/;

export function buildFacilityModel(input: TopologyInput): BuildResult {
  const unit = input.facility.frame_unit.trim();
  const scale = SCENE_UNITS_PER_FRAME_UNIT[unit];
  if (scale === undefined) return { ok: false, reason: 'unsupported_frame_unit', detail: unit };
  if (input.assetsFrameUnit.trim() !== unit) return { ok: false, reason: 'invalid', detail: 'frame_unit differs between /api/facility and /api/assets' };

  const live = input.assets.filter((a) => a.retired_at === null);
  const seen = new Set<string>();
  for (const a of live) {
    if (seen.has(a.external_id)) return { ok: false, reason: 'invalid', detail: `duplicate external_id ${a.external_id}` };
    seen.add(a.external_id);
  }

  const unplaced: UnplacedAsset[] = [];
  const zonesRaw = live.filter((a) => a.asset_type === 'zone');
  const placedZones = new Map<string, Asset>();
  for (const z of zonesRaw) {
    if (z.pose === null) unplaced.push({ assetId: z.id, externalId: z.external_id, assetType: z.asset_type, reason: 'no_pose' });
    else placedZones.set(z.external_id, z);
  }

  const rackRows: Array<{ asset: Asset; zoneExternalId: string }> = [];
  for (const r of live.filter((a) => a.asset_type === 'rack')) {
    if (r.pose === null) {
      unplaced.push({ assetId: r.id, externalId: r.external_id, assetType: r.asset_type, reason: 'no_pose' });
      continue;
    }
    const parent = r.located_in?.parent_external_id ?? null;
    if (parent === null || !placedZones.has(parent)) {
      unplaced.push({ assetId: r.id, externalId: r.external_id, assetType: r.asset_type, reason: 'no_zone' });
      continue;
    }
    rackRows.push({ asset: r, zoneExternalId: parent });
  }

  if (rackRows.length === 0) return { ok: false, reason: 'empty' };
  if (rackRows.length !== EXPECTED_RACK_COUNT) {
    return { ok: false, reason: 'count_mismatch', detail: `${rackRows.length} placed racks, expected ${EXPECTED_RACK_COUNT}` };
  }

  // Deterministic order from the poses: zones left to right; racks by zone, then row (z), then x.
  const zoneOrder = [...placedZones.values()].sort((a, b) => a.pose!.x - b.pose!.x || a.external_id.localeCompare(b.external_id));
  const zoneIndex = new Map(zoneOrder.map((z, i) => [z.external_id, i]));
  const racks: RackDef[] = rackRows
    .map(({ asset: a, zoneExternalId }) => {
      const p = a.pose!;
      const rowMatch = ROW_RE.exec(a.external_id);
      const rack: RackDef = {
        rackId: a.external_id,
        zoneId: zoneExternalId,
        rowId: rowMatch ? rowMatch[1] : '',
        position: [p.x * scale, p.y * scale, p.z * scale],
        size: [RACK_BOX_M[0], RACK_BOX_M[1], RACK_BOX_M[2]],
        assetId: a.id,
        externalId: a.external_id,
        name: a.name,
        assetType: a.asset_type,
        zoneExternalId,
        pose: { x: p.x, y: p.y, z: p.z, rotationDeg: p.rotation_deg, validFrom: p.valid_from },
      };
      return rack;
    })
    .sort(
      (a, b) =>
        zoneIndex.get(a.zoneId)! - zoneIndex.get(b.zoneId)! || a.position[2] - b.position[2] || a.position[0] - b.position[0] || a.rackId.localeCompare(b.rackId),
    );

  const zones: ZoneDef[] = zoneOrder.map((z) => {
    const mine = racks.filter((r) => r.zoneId === z.external_id);
    const halfW = RACK_BOX_M[0] / 2;
    const halfD = RACK_BOX_M[2] / 2;
    const minX = Math.min(...mine.map((r) => r.position[0] - halfW), z.pose!.x * scale);
    const maxX = Math.max(...mine.map((r) => r.position[0] + halfW), z.pose!.x * scale);
    const minZ = Math.min(...mine.map((r) => r.position[2] - halfD), z.pose!.z * scale);
    const maxZ = Math.max(...mine.map((r) => r.position[2] + halfD), z.pose!.z * scale);
    return {
      zoneId: z.external_id,
      label: z.name,
      assetId: z.id,
      bounds: {
        centerX: (minX + maxX) / 2,
        centerZ: (minZ + maxZ) / 2,
        width: maxX - minX + 2 * ZONE_OUTLINE_PADDING_M,
        depth: maxZ - minZ + 2 * ZONE_OUTLINE_PADDING_M,
      },
    };
  });

  return { ok: true, model: { zones, racks, frameUnit: unit, frameNote: input.facility.frame_note, unplaced } };
}
