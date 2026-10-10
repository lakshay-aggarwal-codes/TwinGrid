/** FE-15: the selected scenario is remembered by its opaque backend id only (never by label, position or parsed content). */
export const SELECTION_KEY = 'twingrid.scenario.selected';

type Store = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

function defaultStore(): Store | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function loadSelectedId(store: Store | null = defaultStore()): string | null {
  try {
    const v = store?.getItem(SELECTION_KEY);
    return typeof v === 'string' && v !== '' ? v : null;
  } catch {
    return null;
  }
}

export function saveSelectedId(id: string | null, store: Store | null = defaultStore()): void {
  try {
    if (id === null) store?.removeItem(SELECTION_KEY);
    else store?.setItem(SELECTION_KEY, id);
  } catch {
    // Storage unavailable: the selection simply is not remembered.
  }
}

export type Resolved = { status: 'none' } | { status: 'selected'; id: string } | { status: 'missing'; id: string };

/** A remembered id that the backend no longer lists is reported as missing, never silently replaced by another scenario. */
export function resolveSelection(savedId: string | null, listedIds: readonly string[]): Resolved {
  if (savedId === null) return { status: 'none' };
  return listedIds.includes(savedId) ? { status: 'selected', id: savedId } : { status: 'missing', id: savedId };
}
