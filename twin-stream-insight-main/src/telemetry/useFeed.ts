import { createContext, useCallback, useContext, useRef, useSyncExternalStore } from 'react';
import type { FeedStore, FeedView } from './feedStore';

export const FeedStoreContext = createContext<FeedStore | null>(null);

export function useFeedStore(): FeedStore {
  const store = useContext(FeedStoreContext);
  if (!store) throw new Error('useFeed must be used inside <SimulationProvider>');
  return store;
}

export function shallowEqual<T extends object>(a: T, b: T): boolean {
  if (Object.is(a, b)) return true;
  const ka = Object.keys(a) as (keyof T)[];
  return ka.length === Object.keys(b).length && ka.every((k) => Object.is(a[k], b[k]));
}

/**
 * Subscribe to a slice of the feed. The component re-renders only when the SELECTED value changes (per `isEqual`,
 * default `Object.is`): a tick that changes `pue` does not re-render a subscriber that selects `cooling_mode`.
 *
 *   const mode = useFeed((v) => v.frame?.value.cooling_mode);
 *   const fresh = useFeed((v) => v.freshness.state);
 *   const slice = useFeed((v) => ({ a: ..., b: ... }), shallowEqual);
 */
export function useFeed<S>(selector: (view: FeedView) => S, isEqual: (a: S, b: S) => boolean = Object.is, store?: FeedStore): S {
  const contextStore = useContext(FeedStoreContext);
  const feed = store ?? contextStore;
  if (!feed) throw new Error('useFeed must be used inside <SimulationProvider>');

  const cache = useRef<{ view: FeedView; selector: (v: FeedView) => S; selected: S } | null>(null);

  const getSnapshot = useCallback((): S => {
    const view = feed.getView();
    const prev = cache.current;
    if (prev && prev.view === view && prev.selector === selector) return prev.selected;
    const next = selector(view);
    const selected = prev && isEqual(prev.selected, next) ? prev.selected : next;
    cache.current = { view, selector, selected };
    return selected;
  }, [feed, selector, isEqual]);

  return useSyncExternalStore(feed.subscribe, getSnapshot, getSnapshot);
}
