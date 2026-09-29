import { useCallback, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import gsap from "gsap";
import { MOTION, motionDuration } from "@/three/motion";
import { loadAnalyticsPage } from "@/pages/lazyPages";
import { RotateContext, type RotateNavigate } from "./rotateContext";

/**
 * Page-to-page transition with swappable styles.
 *
 * Every style has two halves: `out` (old page leaves, then the route changes)
 * and `from -> to` (new page arrives). Only transform / opacity / clip-path /
 * filter are animated, and nothing is left behind afterwards (a lingering
 * transform would offset the WebGL canvas's pointer coordinates).
 *
 * Try styles live: use the dropdown (dev builds) or add ?transition=slide to
 * the URL. The choice is remembered in localStorage. To lock one in, change
 * DEFAULT_VARIANT below.
 */

type VariantName = "rotate" | "fade" | "slide" | "slideUp" | "zoom" | "flip" | "curtain" | "blur" | "none";

interface Variant {
  label: string;
  /** Multiplier on MOTION.pageRotate for each half. */
  scale: number;
  start?: gsap.TweenVars;
  out: (d: number) => gsap.TweenVars;
  from: (d: number) => gsap.TweenVars;
  to: gsap.TweenVars;
  outEase: string;
  inEase: string;
}

const VARIANTS: Record<VariantName, Variant> = {
  rotate: {
    label: "Door swing",
    scale: 1,
    out: (d) => ({ rotationY: 90 * d }),
    from: (d) => ({ rotationY: -90 * d }),
    to: { rotationY: 0 },
    outEase: "power2.in",
    inEase: "power2.out",
  },
  fade: {
    label: "Crossfade",
    scale: 0.6,
    out: () => ({ opacity: 0 }),
    from: () => ({ opacity: 0 }),
    to: { opacity: 1 },
    outEase: "power1.in",
    inEase: "power1.out",
  },
  slide: {
    label: "Slide + fade (horizontal)",
    scale: 0.8,
    out: (d) => ({ xPercent: -8 * d, opacity: 0 }),
    from: (d) => ({ xPercent: 8 * d, opacity: 0 }),
    to: { xPercent: 0, opacity: 1 },
    outEase: "power2.in",
    inEase: "power3.out",
  },
  slideUp: {
    label: "Rise + fade (vertical)",
    scale: 0.8,
    out: () => ({ yPercent: -5, opacity: 0 }),
    from: () => ({ yPercent: 6, opacity: 0 }),
    to: { yPercent: 0, opacity: 1 },
    outEase: "power2.in",
    inEase: "power3.out",
  },
  zoom: {
    label: "Zoom through",
    scale: 0.8,
    out: () => ({ scale: 0.94, opacity: 0 }),
    from: () => ({ scale: 1.06, opacity: 0 }),
    to: { scale: 1, opacity: 1 },
    outEase: "power2.in",
    inEase: "power2.out",
  },
  flip: {
    label: "Flip (vertical axis)",
    scale: 0.9,
    out: (d) => ({ rotationX: 90 * d }),
    from: (d) => ({ rotationX: -90 * d }),
    to: { rotationX: 0 },
    outEase: "power2.in",
    inEase: "power2.out",
  },
  curtain: {
    label: "Curtain wipe",
    scale: 0.9,
    start: { clipPath: "inset(0% 0% 0% 0%)" },
    out: (d) => ({ clipPath: d > 0 ? "inset(0% 0% 0% 100%)" : "inset(0% 100% 0% 0%)" }),
    from: (d) => ({ clipPath: d > 0 ? "inset(0% 100% 0% 0%)" : "inset(0% 0% 0% 100%)" }),
    to: { clipPath: "inset(0% 0% 0% 0%)" },
    outEase: "power2.inOut",
    inEase: "power2.inOut",
  },
  blur: {
    label: "Blur fade (heavier on GPU)",
    scale: 0.7,
    start: { filter: "blur(0px)" },
    out: () => ({ filter: "blur(14px)", opacity: 0 }),
    from: () => ({ filter: "blur(14px)", opacity: 0 }),
    to: { filter: "blur(0px)", opacity: 1 },
    outEase: "power1.in",
    inEase: "power1.out",
  },
  none: {
    label: "None (instant)",
    scale: 0,
    out: () => ({}),
    from: () => ({}),
    to: {},
    outEase: "none",
    inEase: "none",
  },
};

const DEFAULT_VARIANT: VariantName = "fade";
const STORAGE_KEY = "twingrid.transition";
const CLEAR_PROPS = "transform,opacity,clipPath,filter";
/** Longest we hold the (already faded-out) old page waiting for the next
 * page's code. After this we navigate anyway and the Suspense "Loading…"
 * fallback shows, instead of leaving the user on a blank screen. */
const PRELOAD_TIMEOUT_MS = 1500;

function isVariant(v: string | null): v is VariantName {
  return !!v && v in VARIANTS;
}

function initialVariant(): VariantName {
  try {
    const q = new URLSearchParams(window.location.search).get("transition");
    if (isVariant(q)) {
      localStorage.setItem(STORAGE_KEY, q);
      return q;
    }
    const saved = localStorage.getItem(STORAGE_KEY);
    if (isVariant(saved)) return saved;
  } catch {
    /* storage unavailable: fall through */
  }
  return DEFAULT_VARIANT;
}

export function RotateTransition({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const pageRef = useRef<HTMLDivElement>(null);
  const busy = useRef(false);
  // Direction (+1 / -1) shared between the leaving and arriving halves.
  const arriveDir = useRef<number>(1);
  const firstRender = useRef(true);

  const [variant, setVariant] = useState<VariantName>(initialVariant);
  const variantRef = useRef<VariantName>(variant);
  variantRef.current = variant;

  const showPicker =
    import.meta.env.DEV || new URLSearchParams(window.location.search).has("transition");

  const rotateNavigate = useCallback<RotateNavigate>(
    (to, direction = 1) => {
      const el = pageRef.current;
      const v = VARIANTS[variantRef.current];
      const duration = motionDuration(MOTION.pageRotate) * v.scale;
      if (busy.current) return;
      if (!el || duration === 0 || to === location.pathname) {
        navigate(to);
        return;
      }
      busy.current = true;
      arriveDir.current = direction >= 0 ? 1 : -1;
      document.documentElement.dataset.rotating = "1"; // lets the 3D loop pause
      el.style.willChange = "transform, opacity";
      if (v.start) gsap.set(el, v.start);

      // Fetch the next chunk while the old page leaves, but never wait more
      // than PRELOAD_TIMEOUT_MS for it (slow networks).
      let timer: number | undefined;
      const timeout = new Promise<void>((resolve) => {
        timer = window.setTimeout(resolve, PRELOAD_TIMEOUT_MS);
      });
      const preload = Promise.race([loadAnalyticsPage().catch(() => undefined), timeout]).finally(() =>
        window.clearTimeout(timer),
      );
      const leaving = new Promise<void>((resolve) => {
        gsap.to(el, {
          ...v.out(arriveDir.current),
          duration,
          ease: v.outEase,
          force3D: true,
          onComplete: () => resolve(),
        });
      });

      void Promise.all([leaving, preload]).then(() => {
        navigate(to);
      });
    },
    [navigate, location.pathname],
  );

  // Runs after the new route has rendered: play the arrival half. Also covers
  // browser back/forward (no leaving half, so it plays from the default side).
  useLayoutEffect(() => {
    const el = pageRef.current;
    if (!el) return;
    const v = VARIANTS[variantRef.current];
    const duration = motionDuration(MOTION.pageRotate) * v.scale;
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
    const dir = arriveDir.current;
    arriveDir.current = 1;
    const finish = () => {
      busy.current = false;
      el.style.willChange = "";
      delete document.documentElement.dataset.rotating;
      focusHeading();
    };
    if (duration === 0) {
      gsap.set(el, { clearProps: CLEAR_PROPS });
      finish();
      return;
    }
    el.style.willChange = "transform, opacity";
    const tween = gsap.fromTo(el, v.from(dir), {
      ...v.to,
      duration,
      ease: v.inEase,
      force3D: true,
      // Leave NO transform behind (would offset WebGL pointer coordinates).
      clearProps: CLEAR_PROPS,
      onComplete: finish,
    });
    return () => {
      tween.kill();
      gsap.set(el, { clearProps: CLEAR_PROPS });
      busy.current = false;
      el.style.willChange = "";
      delete document.documentElement.dataset.rotating;
    };
  }, [location.pathname]);

  const value = useMemo(() => rotateNavigate, [rotateNavigate]);

  return (
    <RotateContext.Provider value={value}>
      {/* Outer: perspective (for rotate/flip) + clipping so nothing causes a scrollbar. */}
      <div className="h-screen overflow-hidden bg-background" style={{ perspective: "1600px" }}>
        <div ref={pageRef} className="h-full" style={{ transformOrigin: "50% 50%" }}>
          {children}
        </div>
        {showPicker && (
          <select
            aria-label="Page transition style"
            value={variant}
            onChange={(e) => {
              const next = e.target.value as VariantName;
              setVariant(next);
              try {
                localStorage.setItem(STORAGE_KEY, next);
              } catch {
                /* ignore */
              }
            }}
            className="fixed bottom-3 left-3 z-[9999] rounded-md border border-border bg-card px-2 py-1 text-xs text-foreground shadow"
          >
            {(Object.keys(VARIANTS) as VariantName[]).map((name) => (
              <option key={name} value={name}>
                {VARIANTS[name].label}
              </option>
            ))}
          </select>
        )}
      </div>
    </RotateContext.Provider>
  );
}
