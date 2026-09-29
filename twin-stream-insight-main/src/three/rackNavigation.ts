import { FACILITY_LAYOUT, findRack, type RackDef } from "./facilityLayout";

/**
 * Stage 21: keyboard traversal of the 3D scene (deferred since Stage 3).
 *
 * Pure functions over the static layout so the behaviour is unit-testable
 * without WebGL. Screen directions assume the default camera (Stage 12
 * cameraDefaults: it looks from +z toward the origin), so:
 *   Left/Right -> along a row (x axis), continuing into the next zone
 *   Up/Down    -> between the two rows of the same zone (z axis; Up = far row)
 * Movement stops at the edges rather than wrapping, so the user always
 * knows they reached the end.
 */

export type NavKey = "ArrowLeft" | "ArrowRight" | "ArrowUp" | "ArrowDown" | "Home" | "End";

const NAV_KEYS: readonly string[] = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"];

export function isNavKey(key: string): key is NavKey {
  return NAV_KEYS.includes(key);
}

const ROW_EPSILON = 1e-6;

/** Human-readable name for screen readers, e.g. "Zone A, row 1, rack 3". */
export function describeRack(rackId: string): string {
  const rack = findRack(rackId);
  if (!rack) return rackId;
  const zone = FACILITY_LAYOUT.zones.find((z) => z.zoneId === rack.zoneId);
  const row = rack.rowId.replace(/^row-/, "row ");
  const rackNumber = /rack-(\d+)$/.exec(rack.rackId)?.[1];
  return [zone?.label ?? rack.zoneId, row, rackNumber ? `rack ${rackNumber}` : rack.rackId].join(", ");
}

/** Racks in the same physical row line (same z), left to right across zones. */
function rowLine(rack: RackDef): RackDef[] {
  return FACILITY_LAYOUT.racks
    .filter((r) => Math.abs(r.position[2] - rack.position[2]) < ROW_EPSILON)
    .sort((a, b) => a.position[0] - b.position[0]);
}

/** The rack a nav key moves to. With no current selection, any nav key lands
 * on the first rack; at an edge the current rack is returned unchanged. */
export function nextRackId(currentId: string | null, key: NavKey): string {
  const racks = FACILITY_LAYOUT.racks;
  const first = racks[0].rackId;
  const current = currentId ? findRack(currentId) : undefined;

  if (key === "Home") return first;
  if (key === "End") return racks[racks.length - 1].rackId;
  if (!current) return first;

  if (key === "ArrowLeft" || key === "ArrowRight") {
    const line = rowLine(current);
    const index = line.findIndex((r) => r.rackId === current.rackId);
    const step = key === "ArrowRight" ? 1 : -1;
    return (line[index + step] ?? current).rackId;
  }

  // Up/Down: other rows in the same zone, nearest row first, then nearest in x.
  const dir = key === "ArrowDown" ? 1 : -1; // +z is toward the default camera
  const candidates = racks
    .filter((r) => r.zoneId === current.zoneId && (r.position[2] - current.position[2]) * dir > ROW_EPSILON)
    .sort(
      (a, b) =>
        Math.abs(a.position[2] - current.position[2]) - Math.abs(b.position[2] - current.position[2]) ||
        Math.abs(a.position[0] - current.position[0]) - Math.abs(b.position[0] - current.position[0]),
    );
  return (candidates[0] ?? current).rackId;
}
