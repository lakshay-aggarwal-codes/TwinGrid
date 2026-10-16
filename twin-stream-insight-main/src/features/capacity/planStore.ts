import { useSyncExternalStore } from "react";
import { DEFAULT_PLAN, type Plan } from "./model";

/** The plan being looked at, shared by the Capacity page and the 3D overlay widget. In memory only; not persisted. */
let plan: Plan = DEFAULT_PLAN;
const listeners = new Set<() => void>();

export const planStore = {
  get: (): Plan => plan,
  set(next: Plan): void {
    if (next.addRacks === plan.addRacks && next.kwPerRack === plan.kwPerRack) return;
    plan = next;
    listeners.forEach((l) => l());
  },
  subscribe(l: () => void): () => void {
    listeners.add(l);
    return () => void listeners.delete(l);
  },
  reset(): void {
    plan = DEFAULT_PLAN;
    listeners.forEach((l) => l());
  },
};

export const usePlan = (): Plan => useSyncExternalStore(planStore.subscribe, planStore.get, () => DEFAULT_PLAN);
