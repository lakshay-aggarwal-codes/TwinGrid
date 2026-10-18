import { useEffect } from "react";
import { Html } from "@react-three/drei";
import { useThree } from "@react-three/fiber";
import type { ZoneDef } from "./facilityLayout";
import { STATUS_STYLE, useHeadroomOverlay, zoneLabel } from "./headroomOverlayStore";

/**
 * Task 26: tints each zone's floor with the facility headroom status and labels it with an even share of the headroom.
 * Renders nothing while the overlay is off. The plane is not raycastable (it never intercepts a click or hover) and
 * the scene is redrawn once per state change (`frameloop="demand"`), never per frame.
 */
export function HeadroomOverlay({ zones }: { zones: readonly ZoneDef[] }) {
  const overlay = useHeadroomOverlay();
  const { invalidate } = useThree();
  useEffect(() => {
    invalidate();
  }, [overlay, invalidate]);

  const label = zoneLabel(overlay, zones.length);
  if (!label || overlay.status === null) return null;
  const color = STATUS_STYLE[overlay.status].color;

  return (
    <group name="headroom-overlay">
      {zones.map((zone) => {
        const { centerX, centerZ, width, depth } = zone.bounds;
        return (
          <group key={zone.zoneId}>
            <mesh rotation={[-Math.PI / 2, 0, 0]} position={[centerX, 0.015, centerZ]} raycast={() => null}>
              <planeGeometry args={[width, depth]} />
              <meshBasicMaterial color={color} transparent opacity={0.28} depthWrite={false} />
            </mesh>
            <Html position={[centerX, 0.4, centerZ - depth / 2 - 0.3]} center style={{ pointerEvents: "none" }}>
              <div className="whitespace-nowrap rounded border border-border bg-background/90 px-1.5 py-0.5 text-[10px] text-foreground" data-testid={`headroom-zone-${zone.zoneId}`}>
                {zone.label}: {label}
              </div>
            </Html>
          </group>
        );
      })}
    </group>
  );
}
