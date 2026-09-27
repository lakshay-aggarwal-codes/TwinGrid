import { useEffect, useRef } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { Facility } from "./Facility";
import { useCameraFocus } from "./useCameraFocus";
import type { VisualizationMode } from "./visualizationModes";
import type { StateResponse } from "@/api/apiClient";

export interface FocusRequest {
  rackId: string;
  /** Bumped on every request so double-clicking the *same already-focused*
   * rack still re-triggers the camera tween (a plain rackId string wouldn't
   * change and so wouldn't re-fire the effect below). */
  nonce: number;
}

export interface TwinSceneProps {
  selectedRackId: string | null;
  onSelectRack: (rackId: string) => void;
  onDeselect: () => void;
  onRequestFocus: (rackId: string) => void;
  focusRequest: FocusRequest | null;
  mode: VisualizationMode;
  liveState: StateResponse | null;
}

function SceneContents({
  selectedRackId,
  onSelectRack,
  onDeselect,
  onRequestFocus,
  focusRequest,
  mode,
  liveState,
}: TwinSceneProps) {
  const controlsRef = useRef<OrbitControlsImpl | null>(null);
  const isInteractingRef = useRef(false);
  const { focusOnRack } = useCameraFocus(controlsRef);

  useEffect(() => {
    if (focusRequest) {
      focusOnRack(focusRequest.rackId);
    }
    // Only the request itself should retrigger this -- focusOnRack is stable
    // per the camera/controlsRef it closes over.
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
        liveState={liveState}
      />

      <OrbitControls
        ref={controlsRef}
        makeDefault
        enableDamping
        dampingFactor={0.08}
        minDistance={3}
        maxDistance={40}
        maxPolarAngle={Math.PI / 2.05}
        target={[11, 0, 0]}
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
  return (
    <Canvas
      shadows
      camera={{ position: [16, 14, 22], fov: 50 }}
      onPointerMissed={props.onDeselect}
    >
      <SceneContents {...props} />
    </Canvas>
  );
}
