import { Loader2, MapPinOff } from "lucide-react";
import { FALLBACK_BADGE, FALLBACK_REASON_TEXT, LOADING_BADGE, type Topology } from "./facilityTopology";

interface TopologyBadgeProps {
  topology: Topology;
}

/**
 * FE-14: persistent, DOM-text badge (never only in the canvas) whenever the layout is NOT backend-sourced. Absent when the
 * backend topology is in use. Text + icon shape; the reason is stated, never hidden.
 */
export function TopologyBadge({ topology }: TopologyBadgeProps) {
  if (topology.status === "ready") return null;
  const loading = topology.status === "loading";
  return (
    <div
      role="status"
      data-testid="topology-badge"
      data-topology={topology.status}
      className={`absolute top-3 left-3 flex max-w-[22rem] items-start gap-2 rounded-md border bg-card/90 px-2.5 py-1.5 text-xs text-foreground backdrop-blur-sm ${
        loading ? "border-dotted border-muted-foreground/60" : "border-dashed border-warning"
      }`}
    >
      {loading ? (
        <Loader2 aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin motion-reduce:animate-none" />
      ) : (
        <MapPinOff aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      )}
      <span>
        <span className="font-medium">{loading ? LOADING_BADGE : FALLBACK_BADGE}</span>
        {topology.status === "fallback" && <span className="block text-muted-foreground">{FALLBACK_REASON_TEXT[topology.reason]}</span>}
      </span>
    </div>
  );
}
