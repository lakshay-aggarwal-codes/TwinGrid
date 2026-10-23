import { useCallback, useRef } from "react";

/**
 * A Radix dialog or sheet that is opened by state (no DialogTrigger) has nothing to give focus back to when it closes,
 * so focus falls to <body> and a keyboard user loses their place (WCAG 2.4.3). Spread the result onto the content:
 *   const returnFocus = useReturnFocus();  <SheetContent {...returnFocus}> ... </SheetContent>
 * It remembers what had focus just before the content took it and puts focus back when the content closes. If that
 * control has left the page, Radix's default applies.
 */
export function useReturnFocus() {
  const opener = useRef<HTMLElement | null>(null);
  const onOpenAutoFocus = useCallback(() => {
    const active = typeof document === "undefined" ? null : document.activeElement;
    opener.current = active instanceof HTMLElement && active !== document.body ? active : null;
  }, []);
  const onCloseAutoFocus = useCallback((event: Event) => {
    const el = opener.current;
    opener.current = null;
    if (el && el.isConnected) {
      event.preventDefault();
      el.focus();
    }
  }, []);
  return { onOpenAutoFocus, onCloseAutoFocus };
}
