import type { FacilityLayout } from "./facilityLayout";
import { DEFAULT_CAMERA_POSITION, DEFAULT_CAMERA_TARGET } from "./cameraDefaults";

/**
 * Task 13: named camera framings. Pure maths over the active layout (no three.js, no clock), so it is unit-testable and
 * works for the built-in layout and for a backend topology alike.
 *
 * "Hot aisle" frames the aisle between the two rows of the first zone, looking along it. The layout does not say which
 * aisle is hot (there is no per-aisle thermal data), so this is a framing choice, not a thermal claim.
 */
export const CAMERA_PRESETS = [
  { id: "overview", label: "Overview" },
  { id: "hot-aisle", label: "Hot aisle" },
  { id: "top-down", label: "Top-down" },
] as const;

export type CameraPresetId = (typeof CAMERA_PRESETS)[number]["id"];
export type Vec3 = [number, number, number];
export interface CameraPose {
  position: Vec3;
  target: Vec3;
}

/** OrbitControls limits used by TwinScene; a preset must stay inside them or the controls would snap it. */
export const ORBIT_MIN_DISTANCE = 3;
export const ORBIT_MAX_DISTANCE = 40;

const FOV_DEG = 50;
const ASSUMED_ASPECT = 1.6;

export function isCameraPresetId(value: unknown): value is CameraPresetId {
  return CAMERA_PRESETS.some((p) => p.id === value);
}

export interface LayoutBounds {
  minX: number;
  maxX: number;
  minZ: number;
  maxZ: number;
  centerX: number;
  centerZ: number;
  width: number;
  depth: number;
}

/** Footprint of every rack (their boxes included). An empty layout yields the default target as a zero-size box. */
export function layoutBounds(layout: FacilityLayout): LayoutBounds {
  if (layout.racks.length === 0) {
    const [cx, , cz] = DEFAULT_CAMERA_TARGET;
    return { minX: cx, maxX: cx, minZ: cz, maxZ: cz, centerX: cx, centerZ: cz, width: 0, depth: 0 };
  }
  let minX = Infinity;
  let maxX = -Infinity;
  let minZ = Infinity;
  let maxZ = -Infinity;
  for (const r of layout.racks) {
    minX = Math.min(minX, r.position[0] - r.size[0] / 2);
    maxX = Math.max(maxX, r.position[0] + r.size[0] / 2);
    minZ = Math.min(minZ, r.position[2] - r.size[2] / 2);
    maxZ = Math.max(maxZ, r.position[2] + r.size[2] / 2);
  }
  return { minX, maxX, minZ, maxZ, centerX: (minX + maxX) / 2, centerZ: (minZ + maxZ) / 2, width: maxX - minX, depth: maxZ - minZ };
}

export function distanceBetween(a: Vec3, b: Vec3): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

function clampDistance(pose: CameraPose): CameraPose {
  const d = distanceBetween(pose.position, pose.target);
  if (d >= ORBIT_MIN_DISTANCE && d <= ORBIT_MAX_DISTANCE) return pose;
  const k = (d < ORBIT_MIN_DISTANCE ? ORBIT_MIN_DISTANCE : ORBIT_MAX_DISTANCE) / (d || 1);
  const [tx, ty, tz] = pose.target;
  const [px, py, pz] = pose.position;
  return { target: pose.target, position: [tx + (px - tx) * k, ty + (py - ty) * k, tz + (pz - tz) * k] };
}

export function presetPose(id: CameraPresetId, layout: FacilityLayout): CameraPose {
  const overview: CameraPose = { position: [...DEFAULT_CAMERA_POSITION], target: [...DEFAULT_CAMERA_TARGET] };
  if (id === "overview" || layout.racks.length === 0) return overview;

  if (id === "top-down") {
    const b = layoutBounds(layout);
    const half = Math.tan((FOV_DEG / 2) * (Math.PI / 180));
    const height = Math.max(b.depth / 2 / half, b.width / 2 / (half * ASSUMED_ASPECT)) + 2;
    // A tiny z offset keeps the camera off the exact vertical, where OrbitControls' up vector is undefined.
    return clampDistance({ position: [b.centerX, height, b.centerZ + 0.01], target: [b.centerX, 0, b.centerZ] });
  }

  // hot-aisle
  const zone = layout.zones[0];
  if (!zone) return overview;
  const { centerX, centerZ, width } = zone.bounds;
  return clampDistance({
    position: [centerX - width / 2 - 1, 1.5, centerZ],
    target: [centerX + width * 0.25, 1.2, centerZ],
  });
}
