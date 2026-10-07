import { X } from "lucide-react";
import { RackInspectorContent } from "./RackInspectorContent";
import type { LiveFeed } from "@/three/visualizationModes";

interface SidePanelProps {
  selectedRackId: string | null;
  onDeselect: () => void;
  /** See RackInspectorContent -- optional facility-wide reference data from the stamped live feed (FE-06). */
  feed?: LiveFeed;
}

/**
 * Right-hand "Inspector" rail. Stage 3 wired it to selection state; Stage 5
 * filled in real content for a selection via RackInspectorContent -- Stage 6
 * switched its facility-wide reference data to the true live feed --
 * SidePanel itself stays layout/chrome (header, close button, empty state).
 */
export function SidePanel({ selectedRackId, onDeselect, feed }: SidePanelProps) {
  return (
    <aside aria-label="Rack inspector" className="w-80 border-l border-border bg-sidebar flex flex-col shrink-0">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Inspector</span>
        {selectedRackId && (
          <button
            onClick={onDeselect}
            className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Clear selection"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        {selectedRackId ? (
          <RackInspectorContent rackId={selectedRackId} feed={feed} />
        ) : (
          <p className="text-sm text-muted-foreground">No object selected</p>
        )}
      </div>
    </aside>
  );
}
