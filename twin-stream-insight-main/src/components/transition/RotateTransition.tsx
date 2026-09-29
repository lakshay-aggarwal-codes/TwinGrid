import { useCallback, useLayoutEffect, useMemo, useRef, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import gsap from "gsap";
import { MOTION, motionDuration } from "@/three/motion";
import { RotateContext, type RotateNavigate } from "./rotateContext";

/**
 * Page-to-page "whole page rotates" transition.
 *
 * The routed page lives inside one wrapper that is rotated around the Y axis
 * (a door-swing). Leaving: 0 -> +/-90deg (page edge-on, invisible), then the
 * route changes. Arriving: the new page starts at the opposite -/+90deg and
 * swings to 0. Direction is chosen per navigation so going "in" and coming
 * "back" rotate opposite ways.
 *
 * Timing comes from MOTION (three/motion.ts) and collapses to an instant
 * navigation under prefers-reduced-motion, like every other animation here.
 */

export function RotateTransition({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const pageRef = useRef<HTMLDivElement>(null);
  const busy = useRef(false);
  // Direction of the *arriving* half; set by the leaving half.
  const arriveFrom = useRef<number>(0);
  const firstRender = useRef(true);

  const rotateNavigate = useCallback<RotateNavigate>(
    (to, direction = 1) => {
      const el = pageRef.current;
      const duration = motionDuration(MOTION.pageRotate);
      if (busy.current) return;
      if (!el || duration === 0 || to === location.pathname) {
        navigate(to);
        return;
      }
      busy.current = true;
      arriveFrom.current = -90 * direction;
      gsap.to(el, {
        rotationY: 90 * direction,
        duration,
        ease: "power2.in",
        onComplete: () => navigate(to),
      });
    },
    [navigate, location.pathname],
  );

  // Runs after the new route has rendered: swing the new page in from the
  // opposite side. Also covers browser back/forward (no leaving half then,
  // so it just plays the arrival from the default side).
  useLayoutEffect(() => {
    const el = pageRef.current;
    if (!el) return;
    const duration = motionDuration(MOTION.pageRotate);
    // Stage 17: after a real navigation, move keyboard/screen-reader focus to
    // the new page's heading (not on the very first load, which would steal
    // focus from the browser's own starting point).
    const focusHeading = () => {
      if (firstRender.current) {
        firstRender.current = false;
        return;
      }
      const h1 = el.querySelector("h1");
      if (h1) {
        h1.setAttribute("tabindex", "-1");
        h1.focus({ preventScroll: true });
      }
    };
    const from = arriveFrom.current || -90;
    arriveFrom.current = 0;
    if (duration === 0) {
      busy.current = false;
      focusHeading();
      return;
    }
    const tween = gsap.fromTo(
      el,
      { rotationY: from },
      {
        rotationY: 0,
        duration,
        ease: "power2.out",
        // Leave NO transform behind: a lingering transform would become the
        // containing block for position:fixed descendants and offset the
        // WebGL canvas's pointer coordinates.
        clearProps: "transform",
        onComplete: () => {
          busy.current = false;
          focusHeading();
        },
      },
    );
    return () => {
      tween.kill();
      busy.current = false;
    };
  }, [location.pathname]);

  const value = useMemo(() => rotateNavigate, [rotateNavigate]);

  return (
    <RotateContext.Provider value={value}>
      {/* Outer: perspective + clipping so the swing never causes a scrollbar. */}
      <div className="h-screen overflow-hidden bg-background" style={{ perspective: "1600px" }}>
        <div ref={pageRef} className="h-full will-change-transform" style={{ transformOrigin: "50% 50%" }}>
          {children}
        </div>
      </div>
    </RotateContext.Provider>
  );
}
