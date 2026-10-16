/**
 * Task 23: the one backfill state the app is showing, for UI that sits outside the host that owns it (the status bar).
 * `BackfillHost` is the only writer. It adds no request: it only points at the state the host's backfiller holds.
 */
import { useSyncExternalStore } from 'react';
import { IDLE, type BackfillState, type Backfiller } from './backfill';

let active: Backfiller | null = null;
const listeners = new Set<() => void>();
let unsub: (() => void) | null = null;
const emit = () => listeners.forEach((l) => l());

export function setActiveBackfiller(b: Backfiller): void {
  if (active === b) return;
  unsub?.();
  active = b;
  unsub = b.subscribe(emit);
  emit();
}

/** Clears only if `b` is still the active one, so a late cleanup cannot remove a newer backfiller. */
export function clearActiveBackfiller(b: Backfiller): void {
  if (active !== b) return;
  unsub?.();
  unsub = null;
  active = null;
  emit();
}

const getSnapshot = (): BackfillState => active?.getState() ?? IDLE;
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => void listeners.delete(l);
};

export const useBackfillState = (): BackfillState => useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
