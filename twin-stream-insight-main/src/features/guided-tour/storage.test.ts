import { describe, expect, it } from "vitest";
import { DEFAULT_PREFS, TOUR_STORAGE_KEY, loadTourPrefs, saveTourPrefs } from "./storage";

const memory = (initial?: string) => {
  const data = new Map<string, string>();
  if (initial !== undefined) data.set(TOUR_STORAGE_KEY, initial);
  return { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
};

describe("tour preferences", () => {
  it("gives the defaults (welcome not seen) when nothing is stored", () => {
    expect(loadTourPrefs(memory())).toEqual(DEFAULT_PREFS);
  });

  it("round-trips", () => {
    const s = memory();
    saveTourPrefs({ welcomeSeen: true, resumeStepId: "replay", completed: false }, s);
    expect(loadTourPrefs(s)).toEqual({ welcomeSeen: true, resumeStepId: "replay", completed: false });
  });

  it.each(["not json", "null", "42", '"x"', "[]"])("falls back to the defaults for corrupt content %s", (raw) => {
    expect(loadTourPrefs(memory(raw))).toEqual(DEFAULT_PREFS);
  });

  it("accepts only exact booleans and a non-empty string id", () => {
    expect(loadTourPrefs(memory(JSON.stringify({ welcomeSeen: "yes", resumeStepId: "", completed: 1 })))).toEqual(DEFAULT_PREFS);
  });

  it("never throws when storage is blocked or full", () => {
    const broken = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("full");
      },
    };
    expect(loadTourPrefs(broken)).toEqual(DEFAULT_PREFS);
    expect(() => saveTourPrefs(DEFAULT_PREFS, broken)).not.toThrow();
    expect(loadTourPrefs(null)).toEqual(DEFAULT_PREFS);
    expect(() => saveTourPrefs(DEFAULT_PREFS, null)).not.toThrow();
  });
});
