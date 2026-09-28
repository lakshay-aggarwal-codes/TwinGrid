import { useEffect, useRef } from "react";
import { useThree } from "@react-three/fiber";
import gsap from "gsap";
import { Color, type MeshStandardMaterial } from "three";
import { MOTION, motionDuration } from "./motion";

interface AnimatedMaterialProps {
  color: string;
  emissive: string;
  emissiveIntensity: number;
  roughness?: number;
  metalness?: number;
}

/**
 * Stage 14: a meshStandardMaterial whose color / emissive / emissiveIntensity
 * ease to new values instead of popping. Used for the three things that
 * actually change on a rack and mean something to the operator: hover and
 * selection feedback, the tint changing as the live reading moves, and the
 * tint changing when the view mode changes between tinted modes.
 *
 * The JSX below is given only the FIRST values; every later change is applied
 * by GSAP to the live material, so React never re-applies a target value on
 * top of a running tween. The component's props are the same values the old
 * inline <meshStandardMaterial> took, so Rack's behavior is unchanged apart
 * from the easing. The scene renders on demand (see TwinScene), so each tween
 * frame calls invalidate() to request a render.
 */
export function AnimatedMaterial({ color, emissive, emissiveIntensity, roughness = 0.6, metalness = 0.2 }: AnimatedMaterialProps) {
  const ref = useRef<MeshStandardMaterial>(null);
  const initial = useRef({ color, emissive, emissiveIntensity });
  const { invalidate } = useThree();

  useEffect(() => {
    const material = ref.current;
    if (!material) return;
    const duration = motionDuration(MOTION.material);
    const colorTween = gsap.to(material.color, {
      ...toLinearRgb(color),
      duration,
      ease: "power1.out",
      onUpdate: invalidate,
    });
    const emissiveTween = gsap.to(material.emissive, {
      ...toLinearRgb(emissive),
      duration,
      ease: "power1.out",
    });
    const intensityTween = gsap.to(material, {
      emissiveIntensity,
      duration,
      ease: "power1.out",
    });
    return () => {
      colorTween.kill();
      emissiveTween.kill();
      intensityTween.kill();
    };
  }, [color, emissive, emissiveIntensity, invalidate]);

  return (
    <meshStandardMaterial
      ref={ref}
      color={initial.current.color}
      emissive={initial.current.emissive}
      emissiveIntensity={initial.current.emissiveIntensity}
      roughness={roughness}
      metalness={metalness}
    />
  );
}

/** Parsed through THREE.Color so the tween targets the same linear-space
 * components R3F would have set for this hex string (a raw hex-to-0..1
 * conversion would land on visibly brighter colors). */
function toLinearRgb(hex: string): { r: number; g: number; b: number } {
  const { r, g, b } = new Color(hex);
  return { r, g, b };
}
