import { useCallback, useMemo, useState } from "react";
import type { ThreeEvent } from "@react-three/fiber";
import type { FacilityLayout } from "./facilityLayout";
import { ZoneOutline } from "./ZoneOutline";
import { Rack, type RackVisualState } from "./Rack";
import { computeThermalColors } from "./thermalMapping";
import { currentState, getModeColor, type LiveFeed, type VisualizationMode } from "./visualizationModes";

const FLOOR_COLOR = "#0d0d0f";

export interface FacilityProps {
  selectedRackId: string | null;
  onSelectRack: (rackId: string) => void;
  onDeselect: () => void;
  onFocusRack: (rackId: string) => void;
  /** True while OrbitControls is mid-drag; hover updates are suppressed so
   * hover state doesn't flicker across every rack the pointer sweeps over
   * while orbiting/panning. Owned by TwinScene (it owns the controls). */
  isInteractingRef: React.MutableRefObject<boolean>;
  /** Active visualization mode + the live state it's derived from. Thermal
   * (Stage 7) and the uniform-tint modes (Stage 8) are both computed here,
   * once, from the same `liveState` -- Rack picks whichever its mode branch
   * needs. 'physical' (or a null liveState) renders racks uncolored. */
  mode: VisualizationMode;
  /** FE-14: the active topology (backend-sourced, or the built-in fallback). */
  layout: FacilityLayout;
  /** FE-06: tints derive from `currentState(feed)` only, so stale / disconnected / unavailable / no-data all render
   * the neutral colours (WAITING_COLOR / NEUTRAL) -- a last-known value is never tinted as if it were current. */
  feed: LiveFeed;
}

export function Facility({
  selectedRackId,
  onSelectRack,
  onDeselect,
  onFocusRack,
  isInteractingRef,
  mode,
  layout,
  feed,
}: FacilityProps) {
  const liveState = currentState(feed);
  const [hoveredRackId, setHoveredRackId] = useState<string | null>(null);

  const thermalColors = useMemo(
    () =>
      computeThermalColors(
        liveState ? { inletTempC: liveState.server_inlet_temp_C, outletTempC: liveState.server_outlet_temp_C } : null,
      ),
    [liveState],
  );
  const modeColor =
    mode === "energy" || mode === "cooling" || mode === "sustainability" ? getModeColor(mode, liveState) : undefined;

  const handleHoverStart = useCallback(
    (rackId: string) => {
      if (isInteractingRef.current) return;
      setHoveredRackId(rackId);
    },
    [isInteractingRef],
  );

  const handleHoverEnd = useCallback((rackId: string) => {
    // Only clear if this is still the hovered rack -- guards against an
    // out-of-order pointerout (old rack) arriving after the new rack's
    // pointerover already set a different id.
    setHoveredRackId((current) => (current === rackId ? null : current));
  }, []);

  const handleFloorClick = useCallback(
    (event: ThreeEvent<MouseEvent>) => {
      event.stopPropagation();
      onDeselect();
    },
    [onDeselect],
  );

  return (
    <group>
      {layout.zones.map((zone) => (
        <ZoneOutline key={zone.zoneId} zone={zone} />
      ))}

      {layout.racks.map((rack) => {
        const state: RackVisualState =
          rack.rackId === selectedRackId ? "selected" : rack.rackId === hoveredRackId ? "hovered" : "idle";
        return (
          <Rack
            key={rack.rackId}
            rack={rack}
            state={state}
            onSelect={onSelectRack}
            onFocus={onFocusRack}
            onHoverStart={handleHoverStart}
            onHoverEnd={handleHoverEnd}
            mode={mode}
            thermalColors={thermalColors}
            modeColor={modeColor}
          />
        );
      })}

      {/* Floor plane: clicking empty floor deselects. Canvas's onPointerMissed
          (see TwinScene) covers clicks that miss the floor entirely. */}
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, 0, 0]}
        receiveShadow
        userData={{ type: "floor" }}
        onClick={handleFloorClick}
      >
        <planeGeometry args={[200, 200]} />
        <meshStandardMaterial color={FLOOR_COLOR} roughness={0.9} />
      </mesh>
    </group>
  );
}
