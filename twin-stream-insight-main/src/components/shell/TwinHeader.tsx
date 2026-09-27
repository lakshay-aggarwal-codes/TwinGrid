import { Link } from "react-router-dom";
import { Boxes, Radio } from "lucide-react";
import { LocateControl } from "./LocateControl";
import { ModeSwitcher } from "./ModeSwitcher";
import type { StateResponse } from "@/api/apiClient";
import type { VisualizationMode } from "@/three/visualizationModes";

interface TwinHeaderProps {
  onLocateRack: (rackId: string) => void;
  /** Real live facility state from the WebSocket feed (see useSimulation's
   * `liveState`). Null until the first message arrives -- rendered as an
   * explicit "Connecting" state, never a guessed number (Stage 6). */
  liveState: StateResponse | null;
  /** Active visualization mode (Stage 8) + its setter. */
  mode: VisualizationMode;
  onModeChange: (mode: VisualizationMode) => void;
}

function Reading({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</span>
      <span className="font-mono text-xs text-foreground">{value}</span>
    </div>
  );
}

/** Minimal shell header for the 3D Live Twin page. */
export function TwinHeader({ onLocateRack, liveState, mode, onModeChange }: TwinHeaderProps) {
  const isLive = liveState !== null;

  return (
    <header className="flex items-center justify-between px-6 py-3 border-b border-border bg-card/80 backdrop-blur-sm shrink-0">
      <div className="flex items-center gap-3">
        <div className="h-8 w-8 rounded-md bg-primary/20 flex items-center justify-center">
          <Boxes className="h-5 w-5 text-primary" />
        </div>
        <h1 className="text-lg font-semibold tracking-tight text-foreground">Live Twin</h1>
        <ModeSwitcher mode={mode} onChange={onModeChange} />
      </div>

      {/* Real facility-wide telemetry from the live WebSocket feed. Facility-wide
          only -- never implies anything about a specific rack (see RackInspectorContent
          for how the same distinction is kept in the inspector). */}
      <div className="flex items-center gap-4">
        <Reading label="PUE" value={isLive ? liveState.pue.toFixed(2) : "—"} />
        <Reading label="WUE" value={isLive ? liveState.wue.toFixed(3) : "—"} />
        <Reading label="Mode" value={isLive ? liveState.cooling_mode : "—"} />
        <div className="flex items-center gap-1.5">
          <Radio className={`h-3 w-3 ${isLive ? "text-success" : "text-muted-foreground"}`} />
          <span className={`text-[10px] uppercase tracking-wider ${isLive ? "text-success" : "text-muted-foreground"}`}>
            {isLive ? "Live" : "Connecting"}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <LocateControl onLocate={onLocateRack} />
        <Link to="/legacy" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
          Legacy Dashboard
        </Link>
      </div>
    </header>
  );
}
