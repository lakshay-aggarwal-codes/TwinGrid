import { useCallback, useRef } from "react";
import { useThree } from "@react-three/fiber";
import gsap from "gsap";
import type { Vector3 } from "three";
import { findRack } from "./facilityLayout";

/** The subset of OrbitControls' API this hook needs -- kept structural
 * rather than importing the concrete drei/three-stdlib type, so this file
 * doesn't depend on exactly which OrbitControls implementation is in use. */
export interface FocusableControls {
  target: Vector3;
  update: () => void;
}

interface FocusOptions {
  /** Distance from the rack the camera ends up at. */
  distance?: number;
  durationSeconds?: number;
}

/**
 * Smoothly frames a rack in view using GSAP tweens on the camera position
 * and the OrbitControls target -- no hand-rolled easing/useFrame loop.
 */
export function useCameraFocus(controlsRef: React.MutableRefObject<FocusableControls | null>) {
  const { camera } = useThree();
  const activeTweens = useRef<gsap.core.Tween[]>([]);

  const focusOnRack = useCallback(
    (rackId: string, options: FocusOptions = {}) => {
      const rack = findRack(rackId);
      const controls = controlsRef.current;
      if (!rack || !controls) return;

      const { distance = 3.5, durationSeconds = 1.1 } = options;
      const [rx, ry, rz] = rack.position;

      // Keep the camera's current horizontal approach direction (relative to
      // the current target) rather than snapping to a fixed angle, so the
      // transition reads as "move toward it", not "jump cut".
      const dirX = camera.position.x - controls.target.x;
      const dirZ = camera.position.z - controls.target.z;
      const dirLength = Math.hypot(dirX, dirZ) || 1;
      const normX = dirX / dirLength;
      const normZ = dirZ / dirLength;

      // A prior focus tween still running (rapid double-clicks on different
      // racks) gets cancelled so tweens never fight over the same properties.
      activeTweens.current.forEach((tween) => tween.kill());

      const positionTween = gsap.to(camera.position, {
        x: rx + normX * distance,
        y: ry + distance * 0.6,
        z: rz + normZ * distance,
        duration: durationSeconds,
        ease: "power2.inOut",
      });
      const targetTween = gsap.to(controls.target, {
        x: rx,
        y: ry,
        z: rz,
        duration: durationSeconds,
        ease: "power2.inOut",
        onUpdate: () => controls.update(),
      });

      activeTweens.current = [positionTween, targetTween];
    },
    [camera, controlsRef],
  );

  return { focusOnRack };
}
