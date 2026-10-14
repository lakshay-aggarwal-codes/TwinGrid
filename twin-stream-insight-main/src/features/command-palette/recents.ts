/** Recently run palette commands, remembered by id in localStorage. Storage can be missing or full: never throws. */

export const RECENTS_KEY = "twingrid.palette.recent";
export const MAX_RECENTS = 5;

type Store = Pick<Storage, "getItem" | "setItem">;

function defaultStore(): Store | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function loadRecents(store: Store | null = defaultStore()): string[] {
  try {
    const parsed: unknown = JSON.parse(store?.getItem(RECENTS_KEY) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((v): v is string => typeof v === "string" && v !== "").slice(0, MAX_RECENTS);
  } catch {
    return [];
  }
}

/** Most recent first, no duplicates, capped. Returns the new list even when it could not be saved. */
export function pushRecent(id: string, store: Store | null = defaultStore()): string[] {
  const next = [id, ...loadRecents(store).filter((x) => x !== id)].slice(0, MAX_RECENTS);
  try {
    store?.setItem(RECENTS_KEY, JSON.stringify(next));
  } catch {
    // Not remembered; the palette still works.
  }
  return next;
}
