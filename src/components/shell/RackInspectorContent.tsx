import { AlertCircle } from "lucide-react";
import { StatusMessage } from "./StatusMessage";
import { FACILITY_LAYOUT, findRack } from "@/three/facilityLayout";
import type { StateResponse } from "@/api/apiClient";

interface RackInspectorContentProps {
  rackId: string;
  /** Current facility-aggregate state from the live WebSocket feed (Stage 6),
   * shown only as explicitly-labeled facility-wide context -- never implied
   * to describe this rack specifically. Null until the first message
   * arrives; the panel shows an explicit "connecting" line rather than a
   * placeholder number for that case. */
  liveState?: StateResponse | null;
}

/** Uses the layout's own zone label ("Zone A") so the inspector, the search
 * palette and the screen-reader announcements all name a zone the same way. */
function formatZoneLabel(zoneId: string): string {
  return FACILITY_LAYOUT.zones.find((z) => z.zoneId === zoneId)?.label ?? zoneId;
}

function formatRowLabel(rowId: string): string {
  const match = rowId.match(/^row-(\d+)$/);
  return match ? `Row ${match[1]}` : rowId;
}

const Divider = () => <div className="h-px bg-border" />;

/**
 * Real content for a selected rack: identity + coordinates come straight
 * from facilityLayout.findRack (the single source of truth for rack data --
 * see facilityLayout.ts), and are the only things this panel ever presents
 * as rack-specific facts. There is no per-rack telemetry/status model on
 * the backend (see the Stage 0 audit): rather than derive or imply one from
 * facility-aggregate numbers, that section says plainly that it doesn't
 * exist yet.
 */
export function RackInspectorContent({ rackId, liveState }: RackInspectorContentProps) {
  const rack = findRack(rackId);

  if (!rack) {
    // Selection is always set from a real rack's userData, so this
    // shouldn't happen -- but a selected id that no longer resolves (e.g.
    // the layout changed under it) is worth saying plainly, not silently
    // rendering nothing.
    return <p className="text-sm text-muted-foreground">Rack "{rackId}" not found in the facility layout.</p>;
  }

  const [x, y, z] = rack.position;

  return (
    <div className="space-y-5">
      {/* Identity */}
      <div className="space-y-1">
        <p className="text-sm text-foreground">
          {formatZoneLabel(rack.zoneId)} · {formatRowLabel(rack.rowId)}
        </p>
        <p className="text-xs font-mono text-muted-foreground break-all">{rack.rackId}</p>
      </div>

      <Divider />

      {/* Coordinates */}
      <div className="space-y-1.5">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Position</p>
        <div className="grid grid-cols-3 gap-2 font-mono text-xs text-foreground">
          <div>
            <span className="text-muted-foreground">X </span>
            {x.toFixed(2)}
          </div>
          <div>
            <span className="text-muted-foreground">Y </span>
            {y.toFixed(2)}
          </div>
          <div>
            <span className="text-muted-foreground">Z </span>
            {z.toFixed(2)}
          </div>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Scene-space coordinates (this view's own layout), not a surveyed floor position.
        </p>
      </div>

      <Divider />

      {/* Honest empty state -- see module docstring */}
      <div className="space-y-1.5">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Status</p>
        <div className="flex items-start gap-2 text-xs text-muted-foreground">
          <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          <span>Per-rack telemetry not yet available. The backend currently reports facility-wide values only.</span>
        </div>
      </div>

      <Divider />

      {/* Facility-wide reference, from the real live feed -- see module docstring */}
      <div className="space-y-1">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Facility reference</p>
        <p className="text-[11px] text-muted-foreground">Facility-wide, live -- not specific to this rack.</p>
        {liveState ? (
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-xs text-foreground pt-0.5">
            <div>
              <span className="text-muted-foreground">PUE </span>
              {liveState.pue.toFixed(2)}
            </div>
            <div>
              <span className="text-muted-foreground">WUE </span>
              {liveState.wue.toFixed(3)}
            </div>
            <div className="col-span-2">
              <span className="text-muted-foreground">Mode </span>
              {liveState.cooling_mode}
            </div>
          </div>
        ) : (
          <StatusMessage kind="loading">Connecting to live feed…</StatusMessage>
        )}
      </div>
    </div>
  );
}
