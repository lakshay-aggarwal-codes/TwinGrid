import type { FacilityLayout } from "@/three/facilityLayout";

/** Task 13: pure helpers for `?rack=<id>` and for keyboard movement through the rack list. */
export const RACK_PARAM = "rack";

/** The rack id in `?rack=` if (and only if) it names a rack of the active layout. Anything else is ignored, never trusted. */
export function parseRackParam(search: string, layout: FacilityLayout): string | null {
  const raw = new URLSearchParams(search).get(RACK_PARAM);
  if (raw === null || raw === "") return null;
  return layout.racks.some((r) => r.rackId === raw) ? raw : null;
}

/** `search` with `rack` set (or removed for null); every other parameter is kept as it was. Returns "" or "?...". */
export function withRackParam(search: string, rackId: string | null): string {
  const params = new URLSearchParams(search);
  if (rackId === null) params.delete(RACK_PARAM);
  else params.set(RACK_PARAM, rackId);
  const text = params.toString();
  return text === "" ? "" : `?${text}`;
}

export type ListKey = "ArrowUp" | "ArrowDown" | "Home" | "End";

export function isListKey(key: string): key is ListKey {
  return key === "ArrowUp" || key === "ArrowDown" || key === "Home" || key === "End";
}

/**
 * Where a key moves the highlight in a flat list of ids. Stops at the ends (no wrapping, so the user knows they arrived);
 * with nothing current, Down/Home land on the first item and Up/End on the last. An empty list yields null.
 */
export function moveInList(ids: readonly string[], currentId: string | null, key: ListKey): string | null {
  if (ids.length === 0) return null;
  const last = ids.length - 1;
  if (key === "Home") return ids[0];
  if (key === "End") return ids[last];
  const index = currentId === null ? -1 : ids.indexOf(currentId);
  if (index === -1) return key === "ArrowDown" ? ids[0] : ids[last];
  const next = Math.min(last, Math.max(0, index + (key === "ArrowDown" ? 1 : -1)));
  return ids[next];
}

/** Rack ids in the order the list shows them: zone by zone (layout order), racks in layout order within each zone. */
export function listOrder(layout: FacilityLayout): string[] {
  return layout.zones.flatMap((z) => layout.racks.filter((r) => r.zoneId === z.zoneId).map((r) => r.rackId));
}
