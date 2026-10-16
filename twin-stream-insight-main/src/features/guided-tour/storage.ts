/** What the tour remembers between visits. Nothing personal: three flags in this browser's localStorage. */
export const TOUR_STORAGE_KEY = "twingrid.tour.v1";

export interface TourPrefs {
  /** The first-run welcome has been dismissed or acted on. */
  welcomeSeen: boolean;
  /** Step to continue from after the tour was skipped part-way; null when there is nothing to resume. */
  resumeStepId: string | null;
  /** The whole story has been watched to its end at least once. */
  completed: boolean;
}

export const DEFAULT_PREFS: TourPrefs = { welcomeSeen: false, resumeStepId: null, completed: false };

type StorageLike = Pick<Storage, "getItem" | "setItem">;

const defaultStorage = (): StorageLike | null => {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null; // storage can be blocked entirely
  }
};

/** Never throws: missing, blocked or corrupt storage gives the defaults (so the welcome simply shows). */
export function loadTourPrefs(storage: StorageLike | null = defaultStorage()): TourPrefs {
  if (!storage) return DEFAULT_PREFS;
  try {
    const raw = storage.getItem(TOUR_STORAGE_KEY);
    if (raw === null) return DEFAULT_PREFS;
    const v = JSON.parse(raw) as Partial<TourPrefs> | null;
    if (typeof v !== "object" || v === null) return DEFAULT_PREFS;
    return {
      welcomeSeen: v.welcomeSeen === true,
      resumeStepId: typeof v.resumeStepId === "string" && v.resumeStepId !== "" ? v.resumeStepId : null,
      completed: v.completed === true,
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

/** Best effort: a full or blocked store loses the preference, never the page. */
export function saveTourPrefs(prefs: TourPrefs, storage: StorageLike | null = defaultStorage()): void {
  if (!storage) return;
  try {
    storage.setItem(TOUR_STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    /* ignore */
  }
}
