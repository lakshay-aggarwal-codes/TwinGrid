import { useCallback, useRef } from "react";
import { useThree } from "@react-three/fiber";
import gsap from "gsap";
import type { Vector3 } from "three";
import { findRack, FACILITY_LAYOUT } from "./facilityLayout";
import { DEFAULT_CAMERA_POSITION, DEFAULT_CAMERA_TARGET } from "./cameraDefaults";
import { MOTION, motionDuration } from "./motion";

/** The subset of OrbitControls' API this hook needs -- kept structural
 * rather than importing the concrete drei/three-stdlib type, so this file
 * doesn't depend on exactly which OrbitControls implementation is in use. */
export interface FocusableControls {
  target: Vector3;
  update: () => void;
}

interface FocusOptions {
  /** Distance from the target the camera ends up at. */
  distance?: number;
  durationSeconds?: number;
}

/**
 * Smoothly frames things in view using GSAP tweens on the camera position
 * and the OrbitControls target -- no hand-rolled easing/useFrame loop.
 * focusOnRack and focusOnZone (Stage 11) share one helper so they animate
 * identically; focusOnOverview (Stage 12) returns to the fixed default view.
 *
 * Stage 14: the canvas renders on demand, so every tween frame calls
 * invalidate() -- without it the camera would move but nothing would redraw.
 */
export function useCameraFocus(controlsRef: React.MutableRefObject<FocusableControls | null>) {
  const { camera, invalidate } = useThree();
  const activeTweens = useRef<gsap.core.Tween[]>([]);

  const focusOnPoint = useCallback(
    (x: number, y: number, z: number, options: FocusOptions = {}) => {
      const controls = controlsRef.current;
      if (!controls) return;

      const { distance = 3.5, durationSeconds = motionDuration(MOTION.camera) } = options;

      // Keep the camera's current horizontal approach direction (relative to
      // the current target) rather than snapping to a fixed angle, so the
      // transition reads as "move toward it", not "jump cut".
      const dirX = camera.position.x - controls.target.x;
      const dirZ = camera.position.z - controls.target.z;
      const dirLength = Math.hypot(dirX, dirZ) || 1;
      const normX = dirX / dirLength;
      const normZ = dirZ / dirLength;

      // A prior focus tween still running gets cancelled so tweens never
      // fight over the same properties.
      activeTweens.current.forEach((tween) => tween.kill());

      const positionTween = gsap.to(camera.position, {
        x: x + normX * distance,
        y: y + distance * 0.6,
        z: z + normZ * distance,
        duration: durationSeconds,
        ease: "power2.inOut",
        onUpdate: invalidate,
      });
      const targetTween = gsap.to(controls.target, {
        x,
        y,
        z,
        duration: durationSeconds,
        ease: "power2.inOut",
        onUpdate: () => {
          controls.update();
          invalidate();
        },
      });

      activeTweens.current = [positionTween, targetTween];
    },
    [camera, controlsRef, invalidate],
  );

  const focusOnRack = useCallback(
    (rackId: string, options: FocusOptions = {}) => {
      const rack = findRack(rackId);
      if (!rack) return;
      const [rx, ry, rz] = rack.position;
      focusOnPoint(rx, ry, rz, { distance: 3.5, ...options });
    },
    [focusOnPoint],
  );

  const focusOnZone = useCallback(
    (zoneId: string, options: FocusOptions = {}) => {
      const zone = FACILITY_LAYOUT.zones.find((z) => z.zoneId === zoneId);
      if (!zone) return;
      const { centerX, centerZ, width, depth } = zone.bounds;
      // Wide enough to fit the whole zone footprint, with a floor so a small
      // zone doesn't end up uncomfortably close.
      const distance = Math.max(Math.max(width, depth) * 1.15, 6);
      focusOnPoint(centerX, 0, centerZ, { distance, durationSeconds: motionDuration(1.2), ...options });
    },
    [focusOnPoint],
  );

  /**
   * Frames the whole facility at its default overview angle (Stage 12).
   * There is no per-rack camera target here on purpose -- the backend has no
   * field associating an alert with a specific rack (GET /api/alerts is
   * facility-aggregate only, see IncidentsPanel), so "focus on the incident"
   * can only honestly mean "return to a sensible whole-facility framing",
   * not zooming to an invented rack.
   */
  const focusOnOverview = useCallback(
    (options: FocusOptions = {}) => {
      const controls = controlsRef.current;
      if (!controls) return;

      const { durationSeconds = motionDuration(MOTION.camera) } = options;
      const [px, py, pz] = DEFAULT_CAMERA_POSITION;
      const [tx, ty, tz] = DEFAULT_CAMERA_TARGET;

      activeTweens.current.forEach((tween) => tween.kill());

      const positionTween = gsap.to(camera.position, {
        x: px,
        y: py,
        z: pz,
        duration: durationSeconds,
        ease: "power2.inOut",
        onUpdate: invalidate,
      });
      const targetTween = gsap.to(controls.target, {
        x: tx,
        y: ty,
        z: tz,
        duration: durationSeconds,
        ease: "power2.inOut",
        onUpdate: () => {
          controls.update();
          invalidate();
        },
      });

      activeTweens.current = [positionTween, targetTween];
    },
    [camera, controlsRef, invalidate],
  );

  return { focusOnRack, focusOnZone, focusOnOverview };
}
