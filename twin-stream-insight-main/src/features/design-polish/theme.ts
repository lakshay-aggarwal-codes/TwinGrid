/** Task 21: dark/light theme. Dark is the default (the product's control-room look); light is an explicit user choice. */
export type Theme = "dark" | "light";

export const THEME_STORAGE_KEY = "twingrid.theme";

export function isTheme(value: unknown): value is Theme {
  return value === "dark" || value === "light";
}

/** Pure: the stored value if it is a known theme, else the default. Anything else (tampered/old values) is ignored. */
export function resolveTheme(stored: string | null | undefined): Theme {
  return isTheme(stored) ? stored : "dark";
}

export function readStoredTheme(storage: Pick<Storage, "getItem"> | null = safeStorage()): Theme {
  try {
    return resolveTheme(storage?.getItem(THEME_STORAGE_KEY));
  } catch {
    return "dark";
  }
}

/**
 * Sets `data-theme` (drives the CSS tokens in index.css) and the `light` class on <html>. The `dark` class is
 * deliberately NOT set: shadcn components carry `dark:` variants that have never been active in this app, and turning
 * them on would change the existing dark look.
 */
export function applyTheme(theme: Theme, root: HTMLElement = document.documentElement): void {
  root.dataset.theme = theme;
  root.classList.toggle("light", theme === "light");
}

export function storeTheme(theme: Theme, storage: Pick<Storage, "setItem"> | null = safeStorage()): void {
  try {
    storage?.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    /* storage unavailable: the choice lasts for this page view only */
  }
}

function safeStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}
