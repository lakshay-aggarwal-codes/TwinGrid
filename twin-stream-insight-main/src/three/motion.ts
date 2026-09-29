/**
 * Stage 14: the app's shared motion constants. Every animation in the app
 * (camera focus, panel open/close, rack selection/mode fills) draws its
 * timing from here so the whole UI moves with one feel, all through GSAP.
 */

/** Honors the OS "reduce motion" setting: animations collapse to instant
 * state changes (duration 0) rather than being removed, so the end state is
 * always reached. Read at call time, not import time, so toggling the OS
 * setting takes effect without a reload. */
export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

export const MOTION = {
  /** Camera moves (rack focus, facility overview). */
  camera: 1.1,
  /** Panel slide in. */
  panelIn: 0.22,
  /** Panel slide out -- shorter than in so closing never feels sluggish. */
  panelOut: 0.14,
  /** One half of the page-to-page rotation (out, then in). */
  pageRotate: 0.38,
  /** Rack selection/hover/mode color changes. */
  material: 0.18,
} as const;

/** Duration in seconds, or 0 when the user prefers reduced motion. */
export function motionDuration(seconds: number): number {
  return prefersReducedMotion() ? 0 : seconds;
}
