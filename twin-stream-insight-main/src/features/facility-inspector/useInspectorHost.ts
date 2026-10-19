import { useEffect, useRef } from "react";
import type { FacilityLayout } from "@/three/facilityLayout";
import type { CameraPresetId } from "@/three/cameraPresets";
import { inspectorBridge } from "@/three/inspectorBridge";
import type { VisualizationMode } from "@/three/visualizationModes";
import { parseRackParam, withRackParam } from "./selectionUrl";

export interface InspectorHostOptions {
  layout: FacilityLayout;
  /** `loading` until the topology has resolved (ready or fallback): `?rack=` is judged against the final layout only. */
  topologyLoading: boolean;
  selectedRackId: string | null;
  mode: VisualizationMode;
  /** Select and fly to a rack (the page's existing "focus" handler). */
  onFocusRack: (rackId: string) => void;
  onDeselect: () => void;
  onSetMode: (mode: VisualizationMode) => void;
  onFocusPreset: (preset: CameraPresetId) => void;
  /** Tests only; default is the browser's. */
  win?: Pick<Window, "location" | "history">;
}

/**
 * Task 13: the Live Twin page's one hook for the inspector. It publishes selection/mode to the bridge, registers the
 * handlers the widgets call, reads `?rack=<id>` once the topology is known, and keeps `?rack=` in step with the selection
 * (`history.replaceState`: sharing a link is possible, the back button is not polluted).
 */
export function useInspectorHost(o: InspectorHostOptions): void {
  const { layout, topologyLoading, selectedRackId, mode, onFocusRack, onDeselect, onSetMode, onFocusPreset } = o;
  const win = o.win ?? window;
  const applied = useRef(false);
  const selectedRackIdRef = useRef(selectedRackId);
  selectedRackIdRef.current = selectedRackId;
  // A rack read from the URL that the page has been asked to select but has not selected yet: the write below must wait for it.
  const pendingFromUrl = useRef<string | null>(null);

  useEffect(() => {
    inspectorBridge.publish({ selectedRackId, mode });
  }, [selectedRackId, mode]);

  useEffect(
    () =>
      inspectorBridge.registerActions({
        selectRack: (rackId) => (rackId === null ? onDeselect() : onFocusRack(rackId)),
        setMode: onSetMode,
        flyToPreset: onFocusPreset,
      }),
    [onFocusRack, onDeselect, onSetMode, onFocusPreset],
  );

  useEffect(() => {
    if (applied.current || topologyLoading) return;
    applied.current = true;
    const fromUrl = parseRackParam(win.location.search, layout);
    if (fromUrl !== null) {
      pendingFromUrl.current = fromUrl;
      onFocusRack(fromUrl);
      return;
    }
    // An unknown id is never trusted: drop it from the URL now. The write effect below only re-runs when the selection
    // changes, so without this a stale `?rack=nope` stayed in the address bar (and in copied links) until the user selected something.
    const next = withRackParam(win.location.search, selectedRackIdRef.current);
    if (next !== win.location.search) {
      win.history.replaceState(win.history.state, "", `${win.location.pathname}${next}${win.location.hash}`);
    }
  }, [topologyLoading, layout, onFocusRack, win]);

  useEffect(() => {
    if (!applied.current) return;
    if (pendingFromUrl.current !== null) {
      if (selectedRackId !== pendingFromUrl.current) return;
      pendingFromUrl.current = null;
    }
    const next = withRackParam(win.location.search, selectedRackId);
    if (next === win.location.search) return;
    win.history.replaceState(win.history.state, "", `${win.location.pathname}${next}${win.location.hash}`);
  }, [selectedRackId, win]);
}
