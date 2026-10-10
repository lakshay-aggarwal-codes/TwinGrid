import { useEffect, useRef, type RefObject } from "react";

/**
 * FE-19 (Section 13, Focus): when a panel opens, focus moves to its heading; when it closes, focus returns to the
 * control that was focused when it opened (the header toggle). Focus is only restored if it was LOST with the panel
 * (it fell back to <body>): if the user already moved on (clicked another toggle, opened another panel), nothing is stolen.
 *
 * The heading must be `tabIndex={-1}` and rendered only while `open`.
 */
export function usePanelFocus(open: boolean): RefObject<HTMLHeadingElement> {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const heading = headingRef.current;
    const panel = heading?.closest("aside") ?? null;
    const active = document.activeElement;
    // Do not capture something inside the panel itself (React strict mode re-runs this effect once in development).
    if (active instanceof HTMLElement && active !== document.body && !(panel && panel.contains(active))) {
      returnTo.current = active;
    }
    heading?.focus({ preventScroll: true });
    return () => {
      const target = returnTo.current;
      const lost = document.activeElement === null || document.activeElement === document.body;
      if (lost && target && target.isConnected) {
        returnTo.current = null;
        target.focus({ preventScroll: true });
      }
    };
  }, [open]);

  return headingRef;
}
