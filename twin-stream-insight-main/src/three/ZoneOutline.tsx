import type { ZoneDef } from "./facilityLayout";

const ZONE_LINE_COLOR = "#3a3a3f"; // neutral, matches the app's --border token family

interface ZoneOutlineProps {
  zone: ZoneDef;
}

/**
 * A thin rectangular outline on the floor marking a zone's footprint. Purely
 * cosmetic/orientation -- carries no userData and is not selectable.
 */
export function ZoneOutline({ zone }: ZoneOutlineProps) {
  const { centerX, centerZ, width, depth } = zone.bounds;
  const halfW = width / 2;
  const halfD = depth / 2;

  const points: [number, number, number][] = [
    [centerX - halfW, 0.01, centerZ - halfD],
    [centerX + halfW, 0.01, centerZ - halfD],
    [centerX + halfW, 0.01, centerZ + halfD],
    [centerX - halfW, 0.01, centerZ + halfD],
    [centerX - halfW, 0.01, centerZ - halfD],
  ];

  return (
    <line>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          count={points.length}
          array={new Float32Array(points.flat())}
          itemSize={3}
        />
      </bufferGeometry>
      <lineBasicMaterial color={ZONE_LINE_COLOR} />
    </line>
  );
}
