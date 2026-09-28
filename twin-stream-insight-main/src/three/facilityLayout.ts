/**
 * Static facility floor layout for the 3D digital-twin view.
 *
 * This is a UI-only concept: there is no per-rack model on the backend
 * (the API's DigitalTwin/OptimizationResult/SensorReading models describe
 * the facility in aggregate, not rack-by-rack -- see the Stage 0 audit).
 * The layout below is a plausible, fixed arrangement of zones/rows/racks
 * purely so the 3D scene has individually-selectable objects to click on.
 * Nothing here should be read as, or extended into, real telemetry.
 */

export interface RackDef {
  /** Stable, unique identifier -- the only thing selection is keyed on. */
  rackId: string;
  zoneId: string;
  rowId: string;
  /** World-space center position [x, y, z]. */
  position: [number, number, number];
  /** [width, height, depth] in world units. */
  size: [number, number, number];
}

export interface ZoneDef {
  zoneId: string;
  label: string;
  /** Floor-plan outline on the XZ plane. */
  bounds: { centerX: number; centerZ: number; width: number; depth: number };
}

export interface FacilityLayout {
  zones: ZoneDef[];
  racks: RackDef[];
}

const ZONE_LABELS = ["Zone A", "Zone B", "Zone C"];
const ROWS_PER_ZONE = 2;
const RACKS_PER_ROW = 6;

const RACK_WIDTH = 0.6;
const RACK_HEIGHT = 2.0;
const RACK_DEPTH = 1.0;

const RACK_GAP = 0.35; // between racks along a row
const ROW_GAP = 2.4; // walking aisle between the two rows in a zone
const ZONE_GAP = 3.5; // gap between zones

function buildLayout(): FacilityLayout {
  const zones: ZoneDef[] = [];
  const racks: RackDef[] = [];

  const rowWidth = RACKS_PER_ROW * RACK_WIDTH + (RACKS_PER_ROW - 1) * RACK_GAP;
  const zoneDepth = ROWS_PER_ZONE * RACK_DEPTH + (ROWS_PER_ZONE - 1) * ROW_GAP;

  let cursorX = 0;
  for (let zoneIndex = 0; zoneIndex < ZONE_LABELS.length; zoneIndex++) {
    const zoneId = `zone-${zoneIndex + 1}`;
    const zoneCenterX = cursorX + rowWidth / 2;

    zones.push({
      zoneId,
      label: ZONE_LABELS[zoneIndex],
      bounds: {
        centerX: zoneCenterX,
        centerZ: 0,
        // Padding so the outline reads as a room, not a shrink-wrap of the racks.
        width: rowWidth + 1.2,
        depth: zoneDepth + 1.2,
      },
    });

    for (let rowIndex = 0; rowIndex < ROWS_PER_ZONE; rowIndex++) {
      const rowId = `row-${rowIndex + 1}`;
      const rowCenterZ = -zoneDepth / 2 + RACK_DEPTH / 2 + rowIndex * (RACK_DEPTH + ROW_GAP);

      for (let rackIndex = 0; rackIndex < RACKS_PER_ROW; rackIndex++) {
        const rackX = cursorX + rackIndex * (RACK_WIDTH + RACK_GAP);
        racks.push({
          rackId: `${zoneId}-${rowId}-rack-${rackIndex + 1}`,
          zoneId,
          rowId,
          position: [rackX + RACK_WIDTH / 2, RACK_HEIGHT / 2, rowCenterZ],
          size: [RACK_WIDTH, RACK_HEIGHT, RACK_DEPTH],
        });
      }
    }

    cursorX += rowWidth + ZONE_GAP;
  }

  return { zones, racks };
}

/** Computed once -- the layout is static, so there's no reason to rebuild it per render. */
export const FACILITY_LAYOUT: FacilityLayout = buildLayout();

export function findRack(rackId: string): RackDef | undefined {
  return FACILITY_LAYOUT.racks.find((r) => r.rackId === rackId);
}

/**
 * Racks grouped by zone. Introduced for Stage 4's header Locate dropdown;
 * since Stage 11 it feeds the command palette's rack results instead (the
 * dropdown itself was retired -- everything it did is reachable via search).
 */
export interface LocateOption {
  rackId: string;
  rowId: string;
  position: [number, number, number];
}

export interface LocateGroup {
  zoneId: string;
  zoneLabel: string;
  racks: LocateOption[];
}

export function listRacksByZone(): LocateGroup[] {
  return FACILITY_LAYOUT.zones.map((zone) => ({
    zoneId: zone.zoneId,
    zoneLabel: zone.label,
    racks: FACILITY_LAYOUT.racks
      .filter((rack) => rack.zoneId === zone.zoneId)
      .map(({ rackId, rowId, position }) => ({ rackId, rowId, position })),
  }));
}
