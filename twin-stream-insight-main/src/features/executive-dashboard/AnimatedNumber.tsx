import { useEffect, useRef } from "react";
import gsap from "gsap";
import { motionDuration, prefersReducedMotion } from "@/three/motion";
import { fmtNumber } from "./format";

/**
 * A number that counts to its new value with gsap. The text is written straight to the DOM node from the tween, so no
 * React state changes per frame. The first value is shown at once, and so is every value when the user prefers
 * reduced motion; the element always ends on the exact final text.
 */
export function AnimatedNumber({ value, decimals, className }: { value: number; decimals: number; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const shown = useRef<number | null>(null);
  const final = fmtNumber(value, decimals) ?? "";

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const from = shown.current;
    shown.current = value;
    if (from === null || from === value || prefersReducedMotion() || motionDuration(0.5) === 0) {
      el.textContent = final;
      return;
    }
    const state = { v: from };
    const tween = gsap.to(state, {
      v: value,
      duration: motionDuration(0.5),
      ease: "power2.out",
      onUpdate: () => {
        el.textContent = fmtNumber(state.v, decimals) ?? final;
      },
      onComplete: () => {
        el.textContent = final;
      },
    });
    return () => {
      tween.kill();
      el.textContent = final;
    };
  }, [value, decimals, final]);

  return (
    <span ref={ref} className={className} data-value={String(value)}>
      {final}
    </span>
  );
}
