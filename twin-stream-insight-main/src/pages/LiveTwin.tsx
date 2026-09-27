import { useCallback, useEffect, useState } from "react";
import { TwinHeader } from "@/components/shell/TwinHeader";
import { SidePanel } from "@/components/shell/SidePanel";
import { ModeLegend } from "@/components/shell/ModeLegend";
import { TwinScene, type FocusRequest } from "@/three/TwinScene";
import { useSimulation } from "@/hooks/useSimulation";
import type { VisualizationMode } from "@/three/visualizationModes";

/**
 * Selection lives here (not inside Rack/Facility) so both the 3D scene and
 * the Inspector rail read off the same single source of truth.
 *
 * Stage 6: the header and inspector now read `liveState` -- the actual
 * live WebSocket feed -- rather than `kpi` (which reflects the *default*
 * slider configuration, fetched once, not a continuously live value; see
 * useSimulation.ts). `liveState` is null until the first message arrives
 * and both consumers render an explicit "connecting" state for that,
 * never a placeholder number.
 *
 * Stage 8: `mode` picks which facility-wide metric (if any) tints the
 * racks -- see three/visualizationModes.ts. 'thermal' is reserved for
 * Stage 7, built separately; merging it in only needs one more case there
 * and one more ModeSwitcher button, not a restructure of this state.
 */
export default function LiveTwin() {
  const [selectedRackId, setSelectedRackId] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState<FocusRequest | null>(null);
  const [mode, setMode] = useState<VisualizationMode>("physical");
  const { liveState } = useSimulation();

  const handleSelectRack = useCallback((rackId: string) => {
    setSelectedRackId(rackId);
  }, []);

  const handleDeselect = useCallback(() => {
    setSelectedRackId(null);
  }, []);

  const handleRequestFocus = useCallback((rackId: string) => {
    // Selecting is implied by "focus on it" too, and a nonce bump makes sure
    // double-clicking the *same* already-focused rack still re-triggers the
    // camera tween (a repeated rackId alone wouldn't look like a new request).
    setSelectedRackId(rackId);
    setFocusRequest((prev) => ({ rackId, nonce: (prev?.nonce ?? 0) + 1 }));
  }, []);

  // Keyboard: Escape deselects without a mouse. Reaching a rack by keyboard
  // in the first place (tab order / arrow-key traversal of the 3D scene)
  // is deferred -- see the Stage 3 report's known limitations.
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSelectedRackId(null);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <div className="flex flex-col h-screen bg-background">
      <TwinHeader onLocateRack={handleRequestFocus} liveState={liveState} mode={mode} onModeChange={setMode} />
      <div className="flex flex-1 min-h-0">
        <div className="flex-1 min-w-0 relative">
          <TwinScene
            selectedRackId={selectedRackId}
            onSelectRack={handleSelectRack}
            onDeselect={handleDeselect}
            onRequestFocus={handleRequestFocus}
            focusRequest={focusRequest}
            mode={mode}
            liveState={liveState}
          />
          <ModeLegend mode={mode} liveState={liveState} />
        </div>
        <SidePanel selectedRackId={selectedRackId} onDeselect={handleDeselect} liveState={liveState} />
      </div>
    </div>
  );
}
