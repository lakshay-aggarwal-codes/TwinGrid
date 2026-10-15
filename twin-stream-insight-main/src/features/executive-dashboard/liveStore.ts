import { useContext, useEffect, useSyncExternalStore } from "react";
import { FeedStoreContext } from "@/telemetry/useFeed";
import type { FeedStore } from "@/telemetry/feedStore";
import type { LiveStatePayload } from "@/api/apiClient";
import { appendSample, sampleFromFrame, type LiveSample } from "./liveSeries";

/**
 * Task 16: one shared buffer of live samples for the dashboard widgets. A single listener per feed store records
 * frames (reference counted), so three widgets mounted together never record a frame three times.
 */

let buffer: readonly LiveSample[] = [];
const listeners = new Set<() => void>();
const recorders = new Map<FeedStore, { count: number; off: () => void }>();

const emit = () => listeners.forEach((l) => l());

export function recordFrame(state: LiveStatePayload, nowMs: number = Date.now()): void {
  const s = sampleFromFrame(state, nowMs);
  if (!s) return;
  const next = appendSample(buffer, s);
  if (next !== buffer) {
    buffer = next;
    emit();
  }
}

/** Tests only. */
export function resetLiveSeries(): void {
  buffer = [];
  emit();
}

export function getLiveSeries(): readonly LiveSample[] {
  return buffer;
}

function acquire(store: FeedStore): () => void {
  let rec = recorders.get(store);
  if (!rec) {
    const off = store.onFrame((f) => recordFrame(f.value));
    rec = { count: 0, off };
    recorders.set(store, rec);
    const current = store.getView().frame;
    if (current) recordFrame(current.value);
  }
  rec.count += 1;
  const held = rec;
  return () => {
    held.count -= 1;
    if (held.count === 0) {
      held.off();
      recorders.delete(store);
    }
  };
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => void listeners.delete(l);
};

/** Live samples received by this tab (oldest first). Empty outside a <SimulationProvider>. */
export function useLiveSeries(): readonly LiveSample[] {
  const store = useContext(FeedStoreContext);
  useEffect(() => (store ? acquire(store) : undefined), [store]);
  return useSyncExternalStore(subscribe, getLiveSeries, getLiveSeries);
}
