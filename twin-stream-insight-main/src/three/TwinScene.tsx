import { useEffect, useRef } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { Facility } from "./Facility";
import { useCameraFocus } from "./useCameraFocus";
import type { LiveFeed, VisualizationMode } from "./visualizationModes";
import type { FacilityLayout } from "./facilityLayout";
import { useFacilityTopology } from "./facilityTopology";
import { TopologyBadge } from "./TopologyBadge";
import { DEFAULT_CAMERA_POSITION, DEFAULT_CAMERA_TARGET } from "./cameraDefaults";

/** `nonce` is bumped on every request so re-selecting the *same* already-
 * focused rack/zone still re-triggers the camera tween (an unchanged id
 * alone wouldn't re-fire the effect below).
 *  - "rack": zoom to one rack (double-click, search).
 *  - "zone": frame a whole zone (Stage 11 search).
 *  - "overview": whole-facility default framing (Stage 12 -- alerts have no
 *    rack to point at, see IncidentsPanel). */
export type FocusRequest =
  | { type: "rack"; rackId: string; nonce: number }
  | { type: "zone"; zoneId: string; nonce: number }
  | { type: "overview"; nonce: number };

export interface TwinSceneProps {
  selectedRackId: string | null;
  onSelectRack: (rackId: string) => void;
  onDeselect: () => void;
  onRequestFocus: (rackId: string) => void;
  focusRequest: FocusRequest | null;
  mode: VisualizationMode;
  /** FE-06: the stamped feed. Only a CURRENT frame tints the scene (see `currentState`). */
  feed: LiveFeed;
}

interface SceneContentsProps extends TwinSceneProps {
  /** FE-14: the active topology, passed in because React context does not cross into the Canvas. */
  layout: FacilityLayout;
}

function SceneContents({
  selectedRackId,
  onSelectRack,
  onDeselect,
  onRequestFocus,
  focusRequest,
  mode,
  feed,
  layout,
}: SceneContentsProps) {
  const controlsRef = useRef<OrbitControlsImpl | null>(null);
  const isInteractingRef = useRef(false);
  const { focusOnRack, focusOnZone, focusOnOverview } = useCameraFocus(controlsRef, layout);

  useEffect(() => {
    if (!focusRequest) return;
    if (focusRequest.type === "rack") {
      focusOnRack(focusRequest.rackId);
    } else if (focusRequest.type === "zone") {
      focusOnZone(focusRequest.zoneId);
    } else {
      focusOnOverview();
    }
    // Only the request itself should retrigger this -- the focus functions
    // are stable per the camera/controlsRef they close over.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusRequest]);

  return (
    <>
      <ambientLight intensity={0.55} />
      <directionalLight position={[12, 18, 10]} intensity={0.9} castShadow />

      <Facility
        selectedRackId={selectedRackId}
        onSelectRack={onSelectRack}
        onDeselect={onDeselect}
        onFocusRack={onRequestFocus}
        isInteractingRef={isInteractingRef}
        mode={mode}
        layout={layout}
        feed={feed}
      />

      <OrbitControls
        ref={controlsRef}
        makeDefault
        enableDamping
        dampingFactor={0.08}
        minDistance={3}
        maxDistance={40}
        maxPolarAngle={Math.PI / 2.05}
        target={DEFAULT_CAMERA_TARGET}
        onStart={() => {
          isInteractingRef.current = true;
        }}
        onEnd={() => {
          isInteractingRef.current = false;
        }}
      />
    </>
  );
}

/**
 * Stage 3 note: OrbitControls here is the same minimal orbit/zoom/pan setup
 * from Stage 2 -- only `ref`, `onStart`/`onEnd` (for hover-drag gating) and
 * `target` were added on top of it; the control scheme itself is untouched.
 */
export function TwinScene(props: TwinSceneProps) {
  // FE-14: the one place the topology is fetched. Until it resolves (or if it fails) the built-in layout is used and flagged.
  const topology = useFacilityTopology();
  return (
    <>
    <Canvas
      shadows
      // Stage 14: render only when something changed (data tick, hover/select,
      // camera move, tween frame) instead of 60x/s while the scene is idle.
      // Every animation here calls invalidate(); OrbitControls invalidates
      // itself on input and damping.
      frameloop="demand"
      camera={{ position: DEFAULT_CAMERA_POSITION, fov: 50 }}
      onPointerMissed={props.onDeselect}
    >
      <SceneContents {...props} layout={topology.layout} />
    </Canvas>
    <TopologyBadge topology={topology} />
    </>
  );
}
