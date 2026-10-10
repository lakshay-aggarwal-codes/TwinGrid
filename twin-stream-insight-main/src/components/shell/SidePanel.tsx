import { useRef } from "react";
import { X } from "lucide-react";
import { RackInspectorContent } from "./RackInspectorContent";
import type { LiveFeed } from "@/three/visualizationModes";
import { useTopology } from "@/three/facilityTopology.ts";

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
  const topology = useTopology();
  // FE-19: clearing the selection removes the button that had focus; focus goes to the inspector heading instead of <body>.
  const headingRef = useRef<HTMLHeadingElement>(null);
  return (
    <aside aria-label="Rack inspector" className="w-80 border-l border-border bg-sidebar flex flex-col shrink-0">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <h2 ref={headingRef} tabIndex={-1} className="text-xs font-semibold uppercase tracking-wider text-muted-foreground focus:outline-none">Inspector</h2>
        {selectedRackId && (
          <button
            onClick={() => {
              onDeselect();
              headingRef.current?.focus({ preventScroll: true });
            }}
            className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="Clear selection"
          >
            <X aria-hidden="true" className="h-4 w-4" />
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        {selectedRackId ? (
          <RackInspectorContent rackId={selectedRackId} feed={feed} />
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">No object selected</p>
            {topology.unplaced.length > 0 && (
              <div data-testid="unplaced-assets" className="space-y-1 text-xs text-muted-foreground">
                <p className="font-semibold uppercase tracking-wider">Unplaced ({topology.unplaced.length})</p>
                <p>These backend assets have no usable position, so they are not drawn:</p>
                <ul className="list-disc pl-4 font-mono">
                  {topology.unplaced.map((u) => (
                    <li key={u.assetId}>
                      {u.externalId} ({u.assetType}) — {u.reason === "no_pose" ? "no pose" : "no placed zone"}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
