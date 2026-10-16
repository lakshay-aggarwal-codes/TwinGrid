import { roleAllows } from "../roles";
import type { FeatureRole } from "../types";

/** One stop of the guided walkthrough. */
export interface TourStep {
  /** Unique, stable: it is what "resume" remembers. */
  id: string;
  /** Absolute path the step is shown on. */
  route: string;
  /** CSS selectors tried in order; the first visible match is highlighted. None found -> a centred caption, never an error. */
  targets?: readonly string[];
  title: string;
  caption: string;
  durationMs: number;
  /** UX gate only (the backend enforces roles): a step above the signed-in role is left out of the tour. */
  minRole?: FeatureRole;
}

export type TourPhase = "idle" | "playing" | "paused" | "finished";

export interface TourState {
  phase: TourPhase;
  steps: readonly TourStep[];
  index: number;
  /** Milliseconds spent on the current step (only counted while playing). */
  elapsedMs: number;
}

export const IDLE_TOUR: TourState = { phase: "idle", steps: [], index: 0, elapsedMs: 0 };

export type TourAction =
  | { type: "start"; steps: readonly TourStep[]; fromIndex?: number }
  | { type: "tick"; dtMs: number }
  | { type: "next" }
  | { type: "prev" }
  | { type: "pause" }
  | { type: "resume" }
  | { type: "toggle" }
  /** Leave the tour; the step and the step list stay so it can be resumed. */
  | { type: "skip" }
  /** Forget the tour entirely. */
  | { type: "close" };

const clampIndex = (i: number, n: number) => Math.min(Math.max(Number.isFinite(i) ? Math.trunc(i) : 0, 0), Math.max(n - 1, 0));
const active = (s: TourState) => s.phase === "playing" || s.phase === "paused";

/** Pure step engine. Never throws; an action that makes no sense in the current phase is ignored. */
export function tourReducer(state: TourState, action: TourAction): TourState {
  switch (action.type) {
    case "start":
      if (action.steps.length === 0) return state;
      return { phase: "playing", steps: action.steps, index: clampIndex(action.fromIndex ?? 0, action.steps.length), elapsedMs: 0 };

    case "tick": {
      if (state.phase !== "playing" || !Number.isFinite(action.dtMs) || action.dtMs <= 0) return state;
      const elapsedMs = state.elapsedMs + action.dtMs;
      const step = state.steps[state.index];
      if (step && elapsedMs >= step.durationMs) return tourReducer(state, { type: "next" });
      return { ...state, elapsedMs };
    }

    case "next":
      if (!active(state)) return state;
      if (state.index >= state.steps.length - 1) return { ...state, phase: "finished", elapsedMs: 0 };
      return { ...state, index: state.index + 1, elapsedMs: 0 };

    case "prev":
      if (!active(state)) return state;
      return { ...state, index: Math.max(state.index - 1, 0), elapsedMs: 0 };

    case "pause":
      return state.phase === "playing" ? { ...state, phase: "paused" } : state;
    case "resume":
      return state.phase === "paused" ? { ...state, phase: "playing" } : state;
    case "toggle":
      return state.phase === "playing" ? { ...state, phase: "paused" } : state.phase === "paused" ? { ...state, phase: "playing" } : state;

    case "skip":
      return active(state) ? { ...state, phase: "idle", elapsedMs: 0 } : state;
    case "close":
      return IDLE_TOUR;
  }
}

export const currentStep = (s: TourState): TourStep | null => (active(s) ? (s.steps[s.index] ?? null) : null);

export const totalDurationMs = (steps: readonly TourStep[]): number => steps.reduce((sum, st) => sum + st.durationMs, 0);

export interface TourProgress {
  /** 1-based, for display. */
  position: number;
  total: number;
  remainingStepMs: number;
  /** 0..1 over the whole tour. */
  fraction: number;
}

export function tourProgress(s: TourState): TourProgress {
  const total = s.steps.length;
  const step = s.steps[s.index];
  if (!step || total === 0) return { position: 0, total, remainingStepMs: 0, fraction: 0 };
  const done = s.steps.slice(0, s.index).reduce((sum, st) => sum + st.durationMs, 0) + Math.min(s.elapsedMs, step.durationMs);
  const all = totalDurationMs(s.steps);
  return { position: s.index + 1, total, remainingStepMs: Math.max(step.durationMs - s.elapsedMs, 0), fraction: all > 0 ? Math.min(done / all, 1) : 0 };
}

/**
 * The steps this user can actually follow: the role may use them AND the page exists (a route that is not registered, or
 * that the role may not open, is dropped so the tour never walks into a 404).
 */
export function resolveSteps(all: readonly TourStep[], role: string | null | undefined, availablePaths: readonly string[]): TourStep[] {
  const norm = (p: string) => (p.length > 1 && p.endsWith("/") ? p.slice(0, -1) : p);
  const paths = new Set(availablePaths.map(norm));
  return all.filter((s) => roleAllows(role, s.minRole) && paths.has(norm(s.route)));
}

/** Where "resume" continues: the remembered step if it is still in the list, otherwise the beginning. */
export function resumeIndex(steps: readonly TourStep[], resumeStepId: string | null): number {
  if (resumeStepId === null) return 0;
  const i = steps.findIndex((s) => s.id === resumeStepId);
  return i < 0 ? 0 : i;
}
