import { afterEach, describe, expect, it } from "vitest";
import { applyTheme, readStoredTheme, resolveTheme, storeTheme, THEME_STORAGE_KEY } from "./theme";

const memory = (initial: Record<string, string> = {}) => {
  const data = { ...initial };
  return { getItem: (k: string) => data[k] ?? null, setItem: (k: string, v: string) => void (data[k] = v), data };
};

afterEach(() => {
  delete document.documentElement.dataset.theme;
  document.documentElement.classList.remove("light");
});

describe("theme", () => {
  it("defaults to dark and ignores unknown stored values", () => {
    expect(resolveTheme(null)).toBe("dark");
    expect(resolveTheme(undefined)).toBe("dark");
    expect(resolveTheme("<script>")).toBe("dark");
    expect(resolveTheme("light")).toBe("light");
    expect(resolveTheme("dark")).toBe("dark");
  });

  it("reads the stored theme and survives unavailable storage", () => {
    expect(readStoredTheme(memory({ [THEME_STORAGE_KEY]: "light" }))).toBe("light");
    expect(readStoredTheme(memory())).toBe("dark");
    expect(readStoredTheme({ getItem: () => { throw new Error("denied"); } })).toBe("dark");
    expect(() => storeTheme("light", { setItem: () => { throw new Error("denied"); } })).not.toThrow();
  });

  it("stores the choice under one key", () => {
    const m = memory();
    storeTheme("light", m);
    expect(m.data[THEME_STORAGE_KEY]).toBe("light");
  });

  it("applyTheme sets data-theme and the matching class, and switching back clears the other", () => {
    applyTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(false); // never set (see applyTheme)
    applyTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(document.documentElement.classList.contains("light")).toBe(false);
  });
});
