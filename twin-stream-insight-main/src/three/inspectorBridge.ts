import { useSyncExternalStore } from "react";
import type { VisualizationMode } from "./visualizationModes";
import type { CameraPresetId } from "./cameraPresets";

/**
 * Task 13: the one-way glue between the 3D scene / Live Twin page and the `facility-inspector` feature.
 *
 * The page owns selection and the view mode and PUBLISHES them here; the scene publishes the hovered rack (from the
 * pointer events it already handles). Feature widgets read this state and call `actions`, which the page registers.
 * Nothing here is touched per frame: hover/selection change on pointer events only.
 */
export interface InspectorBridgeState {
  readonly hoveredRackId: string | null;
  readonly selectedRackId: string | null;
  readonly mode: VisualizationMode;
}

export interface InspectorBridgeActions {
  /** A rack id selects it and flies to it; null clears the selection. */
  selectRack: (rackId: string | null) => void;
  setMode: (mode: VisualizationMode) => void;
  flyToPreset: (preset: CameraPresetId) => void;
}

const INITIAL: InspectorBridgeState = { hoveredRackId: null, selectedRackId: null, mode: "physical" };

let state: InspectorBridgeState = INITIAL;
let registered: InspectorBridgeActions | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((l) => l());
}

export const inspectorBridge = {
  getState: (): InspectorBridgeState => state,
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  publish(patch: Partial<InspectorBridgeState>): void {
    const next = { ...state, ...patch };
    if (next.hoveredRackId === state.hoveredRackId && next.selectedRackId === state.selectedRackId && next.mode === state.mode) return;
    state = next;
    emit();
  },
  /** The page registers its handlers; the returned function removes them (only if they are still the current ones). */
  registerActions(actions: InspectorBridgeActions): () => void {
    registered = actions;
    return () => {
      if (registered === actions) registered = null;
    };
  },
  actions: {
    selectRack: (rackId: string | null) => registered?.selectRack(rackId),
    setMode: (mode: VisualizationMode) => registered?.setMode(mode),
    flyToPreset: (preset: CameraPresetId) => registered?.flyToPreset(preset),
  } satisfies InspectorBridgeActions,
  hasActions: (): boolean => registered !== null,
  /** Tests only. */
  reset(): void {
    state = INITIAL;
    registered = null;
    emit();
  },
};

export function useInspectorBridge<S>(selector: (s: InspectorBridgeState) => S): S {
  return useSyncExternalStore(inspectorBridge.subscribe, () => selector(inspectorBridge.getState()), () => selector(INITIAL));
}
