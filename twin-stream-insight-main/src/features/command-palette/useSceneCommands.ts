import { useEffect, useMemo, useRef } from "react";
import { listRacksByZone, type FacilityLayout } from "@/three/facilityLayout.ts";
import { useTopology } from "@/three/facilityTopology.ts";
import { commandRegistry, type CommandRegistry } from "../commands";
import type { Command } from "../types";

export interface SceneEvent {
  id: string | number;
  message: string;
}

export interface SceneActions {
  onFocusRack: (rackId: string) => void;
  onFocusZone: (zoneId: string) => void;
  onOpenIncidents: () => void;
}

const MAX_ALERTS = 8;

/** Pure: the palette commands for one live-twin scene. Rack and zone ids come from the facility model's layout. */
export function buildSceneCommands(layout: FacilityLayout, events: readonly SceneEvent[], act: SceneActions): Command[] {
  const out: Command[] = [];
  for (const zone of layout.zones) {
    out.push({
      id: `scene.zone.${zone.zoneId}`,
      label: `Focus ${zone.label}`,
      group: "Zones",
      keywords: [zone.zoneId],
      run: () => act.onFocusZone(zone.zoneId),
    });
  }
  for (const group of listRacksByZone(layout)) {
    for (const rack of group.racks) {
      out.push({
        id: `scene.rack.${rack.rackId}`,
        label: `Focus rack ${rack.rackId}`,
        group: "Racks",
        keywords: [group.zoneLabel, rack.rowId, "rack"],
        run: () => act.onFocusRack(rack.rackId),
      });
    }
  }
  const seen = new Set<string>();
  for (const e of events) {
    const id = `scene.alert.${e.id}`;
    if (seen.has(id) || seen.size >= MAX_ALERTS) continue;
    seen.add(id);
    out.push({ id, label: `Alert: ${e.message}`, group: "Alerts", keywords: ["alert", "incident", "event"], run: () => act.onOpenIncidents() });
  }
  return out;
}

/**
 * Called by the live-twin page: contributes its racks, zones and recent alerts to the shared command registry while
 * the page is mounted, so the Ctrl+K palette can search them. The handlers are read through a ref, so a new function
 * identity on each render never re-registers the commands.
 */
export function useSceneCommands(events: readonly SceneEvent[], actions: SceneActions, registry: CommandRegistry = commandRegistry): void {
  const { layout } = useTopology();
  const actionsRef = useRef(actions);
  actionsRef.current = actions;
  const commands = useMemo(
    () =>
      buildSceneCommands(layout, events, {
        onFocusRack: (id) => actionsRef.current.onFocusRack(id),
        onFocusZone: (id) => actionsRef.current.onFocusZone(id),
        onOpenIncidents: () => actionsRef.current.onOpenIncidents(),
      }),
    [layout, events],
  );
  useEffect(() => registry.register("live-twin", commands), [registry, commands]);
}
