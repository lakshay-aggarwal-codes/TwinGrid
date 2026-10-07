import { RotateLink } from "@/components/transition/RotateLink";
import { loadAnalyticsPage } from "@/pages/lazyPages.ts";
import { Boxes, FlaskConical, Wrench, AlertTriangle, Search } from "lucide-react";
import { ModeSwitcher } from "./ModeSwitcher";
import { feedProvenance, toReadout, type LiveFeed, type VisualizationMode } from "@/three/visualizationModes";
import { FreshnessChip, ProvenanceStrip, formatAge } from "@/provenance";

interface TwinHeaderProps {
  /** Stage 11: opens the command palette (replaces the Stage 4 Locate
   * dropdown -- everything it could do is reachable through search). */
  onOpenSearch: () => void;
  /** FE-06: the stamped live feed (frame + CURRENT freshness) from the feed store. No frame yet -> an explicit
   * "Connecting" state, never a guessed number; stale/disconnected -> "Last known" with its age. */
  feed: LiveFeed;
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

function Reading({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</span>
      <span className="font-mono text-xs">{value}</span>
    </div>
  );
}

/** Minimal shell header for the 3D Live Twin page. */
export function TwinHeader({
  onOpenSearch,
  feed,
  mode,
  onModeChange,
  simulationOpen,
  onToggleSimulation,
  operationsOpen,
  onToggleOperations,
  incidentsOpen,
  onToggleIncidents,
}: TwinHeaderProps) {
  // FE-06: everything below derives from the stamped feed. "Live" needs an open socket AND a fresh valid frame
  // (FE-04); the readings are current only then, otherwise "Last known" with their age, or "—".
  const readout = toReadout(feed);
  const view = feedProvenance(feed);
  const lastKnown = readout.mode === "last-known";
  const state = readout.mode === "none" ? null : readout.state;

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
        {/* Origin + freshness + source/time context (FE-05 strip). Mounted once here, so this is the one place
            freshness transitions are announced (polite; "Disconnected" assertive). */}
        <div data-testid="liveness" data-liveness={feed.freshness.state}>
          {feed.frame ? (
            <div data-testid="origin-banner" data-origin-tone={view.origin.state}>
              <ProvenanceStrip view={view} announce />
            </div>
          ) : (
            <FreshnessChip view={view} announce />
          )}
        </div>
        <div
          data-testid="live-readings"
          data-readout={readout.mode}
          className={`flex items-center gap-4 ${
            lastKnown ? "rounded border border-dashed border-muted-foreground/60 px-2 py-0.5 text-muted-foreground" : "text-foreground"
          }`}
        >
          {readout.mode === "last-known" && (
            <span data-testid="last-known" className="text-[10px] uppercase tracking-wider">
              Last known · {formatAge(readout.ageMs)}
            </span>
          )}
          <Reading label="PUE" value={state ? state.pue.toFixed(2) : "—"} />
          <Reading label="WUE" value={state ? state.wue.toFixed(3) : "—"} />
          <div className="hidden min-[1600px]:block">
            <Reading label="Mode" value={state ? state.cooling_mode : "—"} />
          </div>
        </div>
        {simulationOpen && (
          <span data-testid="preview-note" className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Simulation Lab results are previews, not the live feed
          </span>
        )}
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
