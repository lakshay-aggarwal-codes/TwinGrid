import { RotateLink } from "@/components/transition/RotateLink";
import { loadAnalyticsPage } from "@/pages/lazyPages.ts";
import { Boxes, Radio, FlaskConical, Wrench, AlertTriangle, Search } from "lucide-react";
import { ModeSwitcher } from "./ModeSwitcher";
import type { LiveStatePayload } from "@/api/apiClient.ts";
import { originBanner, type LivenessStatus } from "@/hooks/liveness.ts";
import { useSharedSimulation } from "@/hooks/simulationContext";
import type { VisualizationMode } from "@/three/visualizationModes";

interface TwinHeaderProps {
  /** Stage 11: opens the command palette (replaces the Stage 4 Locate
   * dropdown -- everything it could do is reachable through search). */
  onOpenSearch: () => void;
  /** Real live facility state from the WebSocket feed (see useSimulation's
   * `liveState`). Null until the first message arrives -- rendered as an
   * explicit "Connecting" state, never a guessed number (Stage 6). */
  liveState: LiveStatePayload | null;
  /** Active visualization mode (Stage 8) + its setter. */
  mode: VisualizationMode;
  onModeChange: (mode: VisualizationMode) => void;
  /** Stage 9/10: the two left-rail tools. Mutually exclusive -- see LiveTwin.tsx. */
  simulationOpen: boolean;
  onToggleSimulation: () => void;
  operationsOpen: boolean;
  onToggleOperations: () => void;
  /** Stage 12: the compact incident list, same mutually-exclusive left rail. */
  incidentsOpen: boolean;
  onToggleIncidents: () => void;
}

/** Status text/colour per liveness state. "Live" is shown ONLY while the socket is open and payloads are fresh. */
const LIVENESS_DISPLAY: Record<LivenessStatus, { label: string; text: string }> = {
  live: { label: "Live", text: "text-success" },
  stale: { label: "Stale", text: "text-warning" },
  disconnected: { label: "Disconnected", text: "text-destructive" },
  connecting: { label: "Connecting", text: "text-muted-foreground" },
};

function Reading({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</span>
      <span className="font-mono text-xs text-foreground">{value}</span>
    </div>
  );
}

/** Minimal shell header for the 3D Live Twin page. */
export function TwinHeader({
  onOpenSearch,
  liveState,
  mode,
  onModeChange,
  simulationOpen,
  onToggleSimulation,
  operationsOpen,
  onToggleOperations,
  incidentsOpen,
  onToggleIncidents,
}: TwinHeaderProps) {
  // Liveness comes from the socket state + wall time of the last payload (see hooks/liveness.ts),
  // not from "have we ever received a payload".
  const { liveness } = useSharedSimulation();
  const hasData = liveState !== null;
  const status = LIVENESS_DISPLAY[liveness];
  // Last values stay visible while stale/disconnected, but dimmed so they are not read as current.
  const dimmed = liveness === "stale" || liveness === "disconnected";
  const banner = hasData ? originBanner(liveState.origin) : null;

  return (
    <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-6 py-3 border-b border-border bg-card/80 backdrop-blur-sm shrink-0">
      <div className="flex flex-wrap items-center gap-3">
        <div className="h-8 w-8 rounded-md bg-primary/20 flex items-center justify-center">
          <Boxes className="h-5 w-5 text-primary" />
        </div>
        <h1 className="text-lg font-semibold tracking-tight text-foreground">Live Twin</h1>
        <ModeSwitcher mode={mode} onChange={onModeChange} />
        <button
          onClick={onToggleSimulation}
          title="Simulation Lab"
          aria-label="Simulation Lab"
          aria-pressed={simulationOpen}
          className={`flex items-center gap-1.5 px-2 py-1 rounded-md border text-[11px] uppercase tracking-wide transition-colors ${
            simulationOpen ? "border-primary/40 bg-primary/20 text-primary" : "border-border text-muted-foreground hover:text-foreground"
          }`}
        >
          <FlaskConical className="h-3.5 w-3.5" />
          <span className="hidden min-[1600px]:inline">Simulation Lab</span>
        </button>
        <button
          onClick={onToggleOperations}
          title="Operations"
          aria-label="Operations"
          aria-pressed={operationsOpen}
          className={`flex items-center gap-1.5 px-2 py-1 rounded-md border text-[11px] uppercase tracking-wide transition-colors ${
            operationsOpen ? "border-primary/40 bg-primary/20 text-primary" : "border-border text-muted-foreground hover:text-foreground"
          }`}
        >
          <Wrench className="h-3.5 w-3.5" />
          <span className="hidden min-[1600px]:inline">Operations</span>
        </button>
        <button
          onClick={onToggleIncidents}
          title="Incidents"
          aria-label="Incidents"
          aria-pressed={incidentsOpen}
          className={`flex items-center gap-1.5 px-2 py-1 rounded-md border text-[11px] uppercase tracking-wide transition-colors ${
            incidentsOpen ? "border-primary/40 bg-primary/20 text-primary" : "border-border text-muted-foreground hover:text-foreground"
          }`}
        >
          <AlertTriangle className="h-3.5 w-3.5" />
          <span className="hidden min-[1600px]:inline">Incidents</span>
        </button>
      </div>

      {/* Real facility-wide telemetry from the live WebSocket feed. Facility-wide
          only -- never implies anything about a specific rack (see RackInspectorContent
          for how the same distinction is kept in the inspector). */}
      <div className="flex items-center gap-4">
        {banner && (
          <span
            role="status"
            data-testid="origin-banner"
            data-origin-tone={banner.tone}
            title={banner.title}
            className={`rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${
              banner.tone === "simulated" ? "border-warning/40 text-warning" : "border-destructive/40 text-destructive"
            }`}
          >
            {banner.label}
          </span>
        )}
        <div className={`flex items-center gap-4 ${dimmed ? "opacity-50" : ""}`} data-testid="live-readings">
          <Reading label="PUE" value={hasData ? liveState.pue.toFixed(2) : "—"} />
          <Reading label="WUE" value={hasData ? liveState.wue.toFixed(3) : "—"} />
          <div className="hidden min-[1600px]:block">
            <Reading label="Mode" value={hasData ? liveState.cooling_mode : "—"} />
          </div>
        </div>
        <div className="flex items-center gap-1.5" data-testid="liveness" data-liveness={liveness}>
          <Radio className={`h-3 w-3 ${status.text}`} />
          <span className={`text-[10px] uppercase tracking-wider ${status.text}`}>{status.label}</span>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <button
          onClick={onOpenSearch}
          className="flex items-center gap-2 px-2.5 py-1 rounded-md border border-border text-sm text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Search racks, zones and alerts"
          title="Search (Ctrl K)"
        >
          <Search className="h-3.5 w-3.5" />
          <span className="hidden min-[1600px]:inline">Search</span>
          <kbd className="hidden min-[1600px]:inline font-mono text-[10px] rounded border border-border px-1 py-px text-muted-foreground">Ctrl K</kbd>
        </button>
        <RotateLink
          to="/analytics"
          direction={1}
          onPointerEnter={() => void loadAnalyticsPage()}
          onFocus={() => void loadAnalyticsPage()}
          onTouchStart={() => void loadAnalyticsPage()}
          className="text-sm text-muted-foreground hover:text-foreground transition-colors">
          Analytics
        </RotateLink>
      </div>
    </header>
  );
}
