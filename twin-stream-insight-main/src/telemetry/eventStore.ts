/**
 * FE-04: the events list, moved out of `useSimulation` into a store with STABLE ids (a counter, not `Date.now()`,
 * which collided for two events in the same millisecond).
 *
 * `time` is a browser-local display string kept only for existing consumers (it is receipt time, never event time);
 * FE-08 replaces it with server-derived times.
 */
export interface EventItem {
  id: number;
  time: string;
  message: string;
  type: 'info' | 'warning' | 'success' | 'error';
}

export const MAX_EVENTS = 5;

export interface EventStore {
  push(message: string, type: EventItem['type']): void;
  clear(): void;
  subscribe(listener: () => void): () => void;
  /** Referentially stable until the list changes. Treat as read-only. */
  getSnapshot(): EventItem[];
}

export function createEventStore(): EventStore {
  let nextId = 1;
  let events: EventItem[] = []; // replaced, never mutated, so the reference changes only when the list does
  const listeners = new Set<() => void>();
  const emit = () => listeners.forEach((l) => l());

  return {
    push(message, type) {
      const item: EventItem = { id: nextId++, time: new Date().toLocaleTimeString(), message, type };
      events = [item, ...events].slice(0, MAX_EVENTS);
      emit();
    },
    clear() {
      if (events.length === 0) return;
      events = [];
      emit();
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    getSnapshot: () => events,
  };
}
