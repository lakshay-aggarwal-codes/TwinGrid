import { useSyncExternalStore } from "react";
import { GOAL_DEF_BY_ID, defaultGoals, loadGoals, saveGoals, type GoalId, type Goals } from "./goals";

/** Task 16: goal targets shared by the rings and the insight rules, persisted in this browser only. */

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

let goals: Goals = loadGoals(storage());
let storageOk = true;
const listeners = new Set<() => void>();

export function getGoals(): Goals {
  return goals;
}

export function setGoal(id: GoalId, value: number | null): void {
  if (!(id in GOAL_DEF_BY_ID)) return;
  goals = { ...goals, [id]: value };
  storageOk = saveGoals(goals, storage());
  listeners.forEach((l) => l());
}

export function resetGoals(): void {
  goals = defaultGoals();
  storageOk = saveGoals(goals, storage());
  listeners.forEach((l) => l());
}

/** Tests only: re-read storage. */
export function reloadGoals(): void {
  goals = loadGoals(storage());
  listeners.forEach((l) => l());
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => void listeners.delete(l);
};

export function useGoals(): { goals: Goals; storageOk: boolean } {
  const g = useSyncExternalStore(subscribe, getGoals, getGoals);
  return { goals: g, storageOk };
}
