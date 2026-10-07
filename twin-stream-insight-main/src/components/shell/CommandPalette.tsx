import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { MapPin, Boxes, AlertTriangle } from "lucide-react";
import { listRacksByZone } from "@/three/facilityLayout.ts";
import { useTopology } from "@/three/facilityTopology.ts";
import type { EventItem } from "@/hooks/useSimulation";

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onFocusRack: (rackId: string) => void;
  onFocusZone: (zoneId: string) => void;
  /** Real alert/event results. Stage 12 (alerts panel) hasn't landed, so
   * choosing one just opens the Operations Console -- which already lists
   * recent events -- rather than fabricating a rack or detail view for it. */
  onSelectAlert: () => void;
  events: EventItem[];
}

/** "row-2" -> "Row 2" */
function formatRow(rowId: string): string {
  return rowId === "" ? "" : `Row ${rowId.split("-")[1]}`;
}

/** "zone-1-row-2-rack-3" -> "Rack 3" */
function formatRackNumber(rackId: string): string {
  const n = rackId.split("-rack-")[1];
  return n === undefined ? rackId : `Rack ${n}`;
}

/**
 * Searches only what actually exists in this project:
 *  - racks + zones (frontend-only layout convention, see facilityLayout.ts)
 *  - real alert events (useSimulation's `events`, from /api/anomaly_score)
 * The brief also lists "sensors" and "conditions" as searchable -- neither
 * exists as a backend entity (the API only exposes facility-aggregate
 * metrics, and alerts have no rack/sensor association), so they're
 * deliberately left out rather than fabricated to fill out the palette.
 *
 * Rack results use the exact same focus/select path as double-click and the
 * retired header dropdown (LiveTwin's handleRequestFocus) -- one mechanism.
 */
export function CommandPalette({
  open,
  onOpenChange,
  onFocusRack,
  onFocusZone,
  onSelectAlert,
  events,
}: CommandPaletteProps) {
  const { layout } = useTopology();
  const rackGroups = listRacksByZone(layout);
  const run = (action: () => void) => {
    onOpenChange(false);
    action();
  };

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      {/* Radix requires a title/description for screen readers; visually hidden. */}
      <DialogTitle className="sr-only">Search</DialogTitle>
      <DialogDescription className="sr-only">Search racks, zones and alerts, then press Enter to go to one.</DialogDescription>
      <CommandInput placeholder="Search racks, zones, alerts…" />
      <CommandList>
        <CommandEmpty>No matching racks, zones or alerts.</CommandEmpty>

        <CommandGroup heading="Zones">
          {layout.zones.map((zone) => (
            <CommandItem
              key={zone.zoneId}
              value={`${zone.label} ${zone.zoneId}`}
              onSelect={() => run(() => onFocusZone(zone.zoneId))}
            >
              <Boxes className="mr-2 h-4 w-4 text-muted-foreground" />
              {zone.label}
            </CommandItem>
          ))}
        </CommandGroup>

        {rackGroups.map((group) => (
          <CommandGroup key={group.zoneId} heading={`${group.zoneLabel} — Racks`}>
            {group.racks.map((rack) => (
              <CommandItem
                key={rack.rackId}
                // Includes the raw ID so pasting/typing an exact rackId matches too.
                value={`${group.zoneLabel} ${formatRow(rack.rowId)} ${formatRackNumber(rack.rackId)} ${rack.rackId}`}
                onSelect={() => run(() => onFocusRack(rack.rackId))}
              >
                <MapPin className="mr-2 h-4 w-4 text-muted-foreground" />
                {formatRow(rack.rowId) !== "" ? `${formatRow(rack.rowId)} · ` : ""}
                {formatRackNumber(rack.rackId)}
                <span className="ml-auto font-mono text-[10px] text-muted-foreground">{rack.rackId}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        ))}

        {events.length > 0 && (
          <CommandGroup heading="Recent alerts & events">
            {events.slice(0, 8).map((e) => (
              <CommandItem
                key={e.id}
                value={`alert ${e.message} ${e.time}`}
                onSelect={() => run(onSelectAlert)}
              >
                <AlertTriangle className="mr-2 h-4 w-4 text-muted-foreground" />
                <span className="truncate">{e.message}</span>
                <span className="ml-auto font-mono text-[10px] text-muted-foreground">{e.time}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}
      </CommandList>
    </CommandDialog>
  );
}
