import { useSyncExternalStore } from "react";

/**
 * Task 26: the glue between the capacity planner (`features/capacity`) and the 3D scene's headroom overlay, in the same
 * style as `inspectorBridge`: the feature PUBLISHES here, the scene reads. The overlay is facility-level information:
 * the backend model has no per-rack or per-zone limits, so every zone is tinted with the SAME status and labelled with
 * an even share of the facility headroom (an assumption, stated on screen). Nothing here varies by rack.
 */
export type HeadroomStatus = "ok" | "tight" | "exceeded";

export interface HeadroomOverlayState {
  readonly enabled: boolean;
  /** Worst of power / cooling / thermal for the plan on screen; null until a result exists. */
  readonly status: HeadroomStatus | null;
  /** Facility totals in kW (null when the model does not provide them, e.g. no cooling model). */
  readonly powerKw: number | null;
  readonly coolingKw: number | null;
}

const INITIAL: HeadroomOverlayState = { enabled: false, status: null, powerKw: null, coolingKw: null };

/** Colour is never the only cue: each status also has a glyph and a word. */
export const STATUS_STYLE: Readonly<Record<HeadroomStatus, { color: string; glyph: string; word: string }>> = {
  ok: { color: "#16a34a", glyph: "●", word: "ok" },
  tight: { color: "#f59e0b", glyph: "▲", word: "tight" },
  exceeded: { color: "#ef4444", glyph: "■", word: "exceeded" },
};

/** Equal share of a facility total across `parts` zones; null when there is no total or no zone. */
export function evenShare(total: number | null, parts: number): number | null {
  return total === null || !Number.isFinite(total) || parts <= 0 ? null : total / parts;
}

const kw = (v: number | null) => (v === null ? "n/a" : `${v.toFixed(0)} kW`);

/** The text drawn on every zone (and read by tests). */
export function zoneLabel(state: HeadroomOverlayState, zoneCount: number): string | null {
  if (!state.enabled || state.status === null) return null;
  const s = STATUS_STYLE[state.status];
  return `${s.glyph} ${s.word} · even share: power ${kw(evenShare(state.powerKw, zoneCount))}, cooling ${kw(evenShare(state.coolingKw, zoneCount))}`;
}

let state: HeadroomOverlayState = INITIAL;
const listeners = new Set<() => void>();

export const headroomOverlay = {
  getState: (): HeadroomOverlayState => state,
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  publish(patch: Partial<HeadroomOverlayState>): void {
    const next = { ...state, ...patch };
    if (next.enabled === state.enabled && next.status === state.status && next.powerKw === state.powerKw && next.coolingKw === state.coolingKw) return;
    state = next;
    listeners.forEach((l) => l());
  },
  /** Tests, and the feature on unmount. */
  reset(): void {
    state = INITIAL;
    listeners.forEach((l) => l());
  },
};

export function useHeadroomOverlay(): HeadroomOverlayState {
  return useSyncExternalStore(headroomOverlay.subscribe, headroomOverlay.getState, () => INITIAL);
}
