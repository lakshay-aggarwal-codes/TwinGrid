/**
 * The feed store the signed-in app is currently running, for UI that is mounted OUTSIDE <SimulationProvider>
 * (the account bar and its `settings` slot sit beside it, not under it). SimulationProvider sets it when it starts the
 * one feed and clears it when it stops; nothing else may set it. It adds no connection: it only points at the same store.
 */
import { useSyncExternalStore } from 'react';
import type { FeedStore } from './feedStore';

let active: FeedStore | null = null;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export function setActiveFeed(store: FeedStore): void {
  if (active === store) return;
  active = store;
  emit();
}

/** Clears only if `store` is still the active one, so a late cleanup cannot remove a newer feed. */
export function clearActiveFeed(store: FeedStore): void {
  if (active !== store) return;
  active = null;
  emit();
}

export const getActiveFeed = (): FeedStore | null => active;
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => void listeners.delete(l);
};

export function useActiveFeedStore(): FeedStore | null {
  return useSyncExternalStore(subscribe, getActiveFeed, getActiveFeed);
}
