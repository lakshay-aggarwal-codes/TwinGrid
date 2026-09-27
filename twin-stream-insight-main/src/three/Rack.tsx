import { useMemo } from "react";
import { Edges } from "@react-three/drei";
import type { ThreeEvent } from "@react-three/fiber";
import type { RackDef } from "./facilityLayout";
import { WAITING_COLOR, type ThermalColors } from "./thermalMapping";
import type { ModeColor, VisualizationMode } from "./visualizationModes";

// Matches the app's existing neutral/cyan-accent look (see src/index.css --accent:
// 187 100% 50%, --border: 0 0% 18%). No new color language is introduced here --
// hover/selected only change emphasis of the same two hues, never imply status.
const ACCENT_CYAN = "#00e1ff";
const IDLE_BODY = "#26262a";
const IDLE_EDGE = "#4a4a50";
const HOVER_BODY = "#2f2f36";
const SELECTED_BODY = "#35353d";

export type RackVisualState = "idle" | "hovered" | "selected";

interface RackProps {
  rack: RackDef;
  state: RackVisualState;
  onSelect: (rackId: string) => void;
  onFocus: (rackId: string) => void;
  onHoverStart: (rackId: string) => void;
  onHoverEnd: (rackId: string) => void;
  mode: VisualizationMode;
  /** Only meaningful when mode === "thermal" (Stage 7). Same object for
   * every rack in the scene (see thermalMapping.ts) -- null means "no live
   * reading yet", not "no thermal mode". */
  thermalColors: ThermalColors | null;
  /** Only meaningful when mode is energy/cooling/sustainability (Stage 8).
   * Same value for every rack -- there is no per-rack backend data to
   * justify anything else. */
  modeColor?: ModeColor;
}

/**
 * A single rack. Selection is purely data-driven off `rack.rackId` carried in
 * userData -- never off mesh index/position -- so any consumer (SidePanel,
 * camera focus, etc.) can key off the same id without touching this component.
 *
 * Three rendering branches, one per family of view mode:
 *  - "physical": the original Stage 3 three-state look, untouched.
 *  - "thermal": two stacked halves (real inlet/outlet values), or a single
 *    WAITING_COLOR box before the first live reading. Selection/hover show
 *    via the cyan edge alone here -- an emissive cyan wash was tested and
 *    visibly washed out against the bright thermal fill colors.
 *  - energy/cooling/sustainability: a single box tinted by `modeColor`,
 *    with its own emissive glow (matching the fill, not cyan) so idle/
 *    hover/selected stay legible without clashing with the tint.
 */
export function Rack({
  rack,
  state,
  onSelect,
  onFocus,
  onHoverStart,
  onHoverEnd,
  mode,
  thermalColors,
  modeColor,
}: RackProps) {
  const [width, height, depth] = rack.size;

  const physicalBody = useMemo(() => {
    switch (state) {
      case "selected":
        return SELECTED_BODY;
      case "hovered":
        return HOVER_BODY;
      default:
        return IDLE_BODY;
    }
  }, [state]);

  const physicalEmissiveIntensity = state === "selected" ? 0.09 : state === "hovered" ? 0.04 : 0;
  // Thermal fills are bright enough that the same cyan emissive add washes
  // out visibly (verified in Stage 7) -- edge color alone carries selection there.
  const thermalEdge = state === "idle" ? IDLE_EDGE : ACCENT_CYAN;

  const { tintBody, tintEdge, tintEmissive, tintEmissiveIntensity } = useMemo(() => {
    if (!modeColor) {
      return { tintBody: IDLE_BODY, tintEdge: IDLE_EDGE, tintEmissive: ACCENT_CYAN, tintEmissiveIntensity: 0 };
    }
    switch (state) {
      case "selected":
        return { tintBody: modeColor.emphasis, tintEdge: ACCENT_CYAN, tintEmissive: modeColor.emphasis, tintEmissiveIntensity: 0.35 };
      case "hovered":
        return { tintBody: modeColor.emphasis, tintEdge: ACCENT_CYAN, tintEmissive: modeColor.emphasis, tintEmissiveIntensity: 0.22 };
      default:
        return { tintBody: modeColor.base, tintEdge: modeColor.base, tintEmissive: modeColor.emphasis, tintEmissiveIntensity: 0.12 };
    }
  }, [state, modeColor]);

  const handleClick = (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    onSelect(rack.rackId);
  };

  const handleDoubleClick = (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    onFocus(rack.rackId);
  };

  const handlePointerOver = (event: ThreeEvent<PointerEvent>) => {
    event.stopPropagation();
    onHoverStart(rack.rackId);
  };

  const handlePointerOut = (event: ThreeEvent<PointerEvent>) => {
    event.stopPropagation();
    onHoverEnd(rack.rackId);
  };

  return (
    <group
      position={rack.position}
      userData={{ type: "rack", rackId: rack.rackId, zoneId: rack.zoneId, rowId: rack.rowId }}
      onClick={handleClick}
      onDoubleClick={handleDoubleClick}
      onPointerOver={handlePointerOver}
      onPointerOut={handlePointerOut}
    >
      {mode === "physical" && (
        <mesh castShadow receiveShadow>
          <boxGeometry args={rack.size} />
          <meshStandardMaterial
            color={physicalBody}
            emissive={ACCENT_CYAN}
            emissiveIntensity={physicalEmissiveIntensity}
            roughness={0.6}
            metalness={0.2}
          />
          <Edges color={state === "idle" ? IDLE_EDGE : ACCENT_CYAN} threshold={15} />
        </mesh>
      )}

      {mode === "thermal" &&
        (!thermalColors ? (
          // No live reading yet -- explicit waiting color, never a guess.
          <mesh castShadow receiveShadow>
            <boxGeometry args={rack.size} />
            <meshStandardMaterial color={WAITING_COLOR} emissive={ACCENT_CYAN} emissiveIntensity={0} roughness={0.6} metalness={0.2} />
            <Edges color={thermalEdge} threshold={15} />
          </mesh>
        ) : (
          <>
            <mesh castShadow receiveShadow position={[0, -height / 4, 0]}>
              <boxGeometry args={[width, height / 2, depth]} />
              <meshStandardMaterial color={thermalColors.inlet} emissive={ACCENT_CYAN} emissiveIntensity={0} roughness={0.6} metalness={0.2} />
              <Edges color={thermalEdge} threshold={15} />
            </mesh>
            <mesh castShadow receiveShadow position={[0, height / 4, 0]}>
              <boxGeometry args={[width, height / 2, depth]} />
              <meshStandardMaterial color={thermalColors.outlet} emissive={ACCENT_CYAN} emissiveIntensity={0} roughness={0.6} metalness={0.2} />
              <Edges color={thermalEdge} threshold={15} />
            </mesh>
          </>
        ))}

      {(mode === "energy" || mode === "cooling" || mode === "sustainability") && (
        <mesh castShadow receiveShadow>
          <boxGeometry args={rack.size} />
          <meshStandardMaterial
            color={tintBody}
            emissive={tintEmissive}
            emissiveIntensity={tintEmissiveIntensity}
            roughness={0.6}
            metalness={0.2}
          />
          <Edges color={tintEdge} threshold={15} />
        </mesh>
      )}
    </group>
  );
}
