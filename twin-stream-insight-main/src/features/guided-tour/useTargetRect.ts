import { useEffect, useState } from "react";

export interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

const RETRY_MS = 150;
const MAX_TRIES = 20; // ~3 s: a lazily loaded page needs a moment after navigation

/** The first selector that matches an element with a real size, else null. A bad selector is skipped, not thrown. */
export function findTarget(selectors: readonly string[] | undefined, root: ParentNode = document): HTMLElement | null {
  for (const sel of selectors ?? []) {
    let el: Element | null = null;
    try {
      el = root.querySelector(sel);
    } catch {
      continue;
    }
    if (el instanceof HTMLElement) {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) return el;
    }
  }
  return null;
}

const prefersReducedMotion = () => typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const toBox = (el: HTMLElement): Box => {
  const r = el.getBoundingClientRect();
  return { top: r.top, left: r.left, width: r.width, height: r.height };
};

/**
 * Viewport box of the step's target, or null while it cannot be found (the caption is then centred).
 * Looks again for a few seconds (the page may still be loading), scrolls the target into view once, and follows
 * resize and scroll through requestAnimationFrame -- it never touches the 3D scene or React state per frame, only when the box changed.
 */
export function useTargetRect(selectors: readonly string[] | undefined, active: boolean, stepKey: string): Box | null {
  const [box, setBox] = useState<Box | null>(null);

  useEffect(() => {
    if (!active) {
      setBox(null);
      return;
    }
    let el: HTMLElement | null = null;
    let tries = 0;
    let raf = 0;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    const publish = () => {
      raf = 0;
      if (cancelled) return;
      if (el && !el.isConnected) {
        el = null; // the page re-rendered it; look again
        schedule();
        return;
      }
      const next = el ? toBox(el) : null;
      setBox((prev) => (prev && next && prev.top === next.top && prev.left === next.left && prev.width === next.width && prev.height === next.height ? prev : next));
    };
    const onMove = () => {
      if (raf === 0 && typeof requestAnimationFrame === "function") raf = requestAnimationFrame(publish);
    };
    const resolve = () => {
      retry = null;
      if (cancelled) return;
      el = findTarget(selectors);
      if (el) {
        if (typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "center", inline: "nearest", behavior: prefersReducedMotion() ? "auto" : "smooth" });
        publish();
      } else if (tries++ < MAX_TRIES) {
        retry = setTimeout(resolve, RETRY_MS);
      } else {
        setBox(null);
      }
    };
    function schedule() {
      if (retry === null) retry = setTimeout(resolve, RETRY_MS);
    }

    setBox(null);
    resolve();
    window.addEventListener("resize", onMove);
    window.addEventListener("scroll", onMove, true);
    return () => {
      cancelled = true;
      if (retry !== null) clearTimeout(retry);
      if (raf !== 0 && typeof cancelAnimationFrame === "function") cancelAnimationFrame(raf);
      window.removeEventListener("resize", onMove);
      window.removeEventListener("scroll", onMove, true);
    };
    // `selectors` is a stable per-step array; `stepKey` changes with the step.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, stepKey]);

  return box;
}
