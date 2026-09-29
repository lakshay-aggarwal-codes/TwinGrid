import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import gsap from "gsap";
import { TwinHeader } from "@/components/shell/TwinHeader";
import { SidePanel } from "@/components/shell/SidePanel";
import { ModeLegend } from "@/components/shell/ModeLegend";
import { SimulationPanel } from "@/components/shell/SimulationPanel";
import { OperationsConsole } from "@/components/shell/OperationsConsole";
import { IncidentsPanel } from "@/components/shell/IncidentsPanel";
import { CommandPalette } from "@/components/shell/CommandPalette";
import { ReportDialog } from "@/components/shell/ReportDialog";
import { TwinScene, type FocusRequest } from "@/three/TwinScene";
import { SceneErrorBoundary } from "@/three/SceneErrorBoundary";
import { MOTION, motionDuration } from "@/three/motion";
import type { Report } from "@/reports/reports";
import { useSimulation } from "@/hooks/useSimulation";
import type { VisualizationMode } from "@/three/visualizationModes";

type LeftPanel = "none" | "simulation" | "operations" | "incidents";

/**
 * Selection lives here (not inside Rack/Facility) so both the 3D scene and
 * the Inspector rail read off the same single source of truth.
 *
 * Stage 6: the header and inspector now read `liveState` -- the actual
 * live WebSocket feed -- rather than `kpi` (which reflects the *default*
 * slider configuration, fetched once, not a continuously live value; see
 * useSimulation.ts). `liveState` is null until the first message arrives
 * and both consumers render an explicit "connecting" state for that,
 * never a placeholder number.
 *
 * Stage 8: `mode` picks which facility-wide metric (if any) tints the
 * racks -- see three/visualizationModes.ts.
 *
 * Stage 9/10: `leftPanel` picks which single left-rail tool is open
 * (Simulation Lab or the Operations Console) -- mutually exclusive so the
 * viewport never has to shrink for both at once. Confirmed with the user
 * before building Stage 10: there is no LLM/agent backend in this project,
 * so the console surfaces real trained-model endpoints (anomaly detector,
 * PPO cooling optimizer) directly rather than any agent/reasoning layer.
 *
 * Stage 12: `leftPanel` gained a third option, "incidents" -- a compact list
 * of real alerts (GET /api/alerts). Selecting one calls `handleFocusFacility`
 * (an "overview" `focusRequest`) rather than focusing a rack: the
 * backend's alerts are facility-aggregate, with no field associating an
 * alert with a specific rack, so there is no rack to zoom to -- see
 * IncidentsPanel and three/useCameraFocus.focusOnOverview.
 *
 * Stage 13: `report` holds the one open generated report. Triggers live
 * where the data lives (Operations Console, Simulation Lab, Incidents,
 * Sustainability legend) and all funnel into this single viewer.
 */
export default function LiveTwin() {
  const [selectedRackId, setSelectedRackId] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState<FocusRequest | null>(null);
  const [mode, setMode] = useState<VisualizationMode>("physical");
  const [leftPanel, setLeftPanel] = useState<LeftPanel>("none");
  const [searchOpen, setSearchOpen] = useState(false);
  // Stage 13: the currently open generated report (null = viewer closed).
  // Each panel builds its own report from data it already holds and hands it
  // up here; a report is a snapshot, so it is never recomputed while open.
  const [report, setReport] = useState<Report | null>(null);
  const { liveState, config, anomalyScore, latestAnomaly, events } = useSimulation();

  // Stage 14: panel open/close motion. `leftPanel` is what the header says
  // (immediate); `shownPanel` is what is mounted, which lags on close so the
  // panel can slide out before unmounting. Only opacity + a small x offset
  // animate (never width), so the canvas resizes once, not on every frame.
  const [shownPanel, setShownPanel] = useState<LeftPanel>("none");
  const railRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (leftPanel === shownPanel) return;
    if (leftPanel !== "none" || !railRef.current) {
      setShownPanel(leftPanel);
      return;
    }
    const tween = gsap.to(railRef.current, {
      opacity: 0,
      x: -12,
      duration: motionDuration(MOTION.panelOut),
      ease: "power1.in",
      onComplete: () => setShownPanel("none"),
    });
    return () => {
      tween.kill();
    };
  }, [leftPanel, shownPanel]);

  useLayoutEffect(() => {
    if (shownPanel === "none" || !railRef.current) return;
    const tween = gsap.fromTo(
      railRef.current,
      { opacity: 0, x: -12 },
      { opacity: 1, x: 0, duration: motionDuration(MOTION.panelIn), ease: "power2.out", clearProps: "opacity,transform" },
    );
    return () => {
      tween.kill();
    };
  }, [shownPanel]);

  const handleSelectRack = useCallback((rackId: string) => {
    setSelectedRackId(rackId);
  }, []);

  const handleDeselect = useCallback(() => {
    setSelectedRackId(null);
  }, []);

  const handleRequestFocus = useCallback((rackId: string) => {
    // Selecting is implied by "focus on it" too, and a nonce bump makes sure
    // double-clicking the *same* already-focused rack still re-triggers the
    // camera tween (a repeated rackId alone wouldn't look like a new request).
    setSelectedRackId(rackId);
    setFocusRequest((prev) => ({ type: "rack", rackId, nonce: (prev?.nonce ?? 0) + 1 }));
  }, []);

  // Stage 12: incidents have no rack to point at (see class doc above), so
  // this deliberately does NOT touch selectedRackId -- only the camera moves.
  const handleFocusFacility = useCallback(() => {
    setFocusRequest((prev) => ({ type: "overview", nonce: (prev?.nonce ?? 0) + 1 }));
  }, []);

  // Stage 11: zones are camera targets only -- selection/inspector are
  // rack-specific, so framing a zone selects nothing.
  const handleFocusZone = useCallback((zoneId: string) => {
    setFocusRequest((prev) => ({ type: "zone", zoneId, nonce: (prev?.nonce ?? 0) + 1 }));
  }, []);

  // Keyboard: Escape deselects without a mouse. Reaching a rack by keyboard
  // in the first place (tab order / arrow-key traversal of the 3D scene)
  // is deferred -- see the Stage 3 report's known limitations.
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSelectedRackId(null);
      }
      // Standard command-palette shortcut (Stage 11).
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <div className="flex flex-col h-full bg-background">
      <TwinHeader
        onOpenSearch={() => setSearchOpen(true)}
        liveState={liveState}
        mode={mode}
        onModeChange={setMode}
        simulationOpen={leftPanel === "simulation"}
        onToggleSimulation={() => setLeftPanel((p) => (p === "simulation" ? "none" : "simulation"))}
        operationsOpen={leftPanel === "operations"}
        onToggleOperations={() => setLeftPanel((p) => (p === "operations" ? "none" : "operations"))}
        incidentsOpen={leftPanel === "incidents"}
        onToggleIncidents={() => setLeftPanel((p) => (p === "incidents" ? "none" : "incidents"))}
      />
      <div className="flex flex-1 min-h-0">
        {/* Always mounted (each panel returns null when closed) so panel state --
            scenario sliders, optimizer results -- survives close/open exactly as before. */}
        <div ref={railRef} className="flex shrink-0">
          <SimulationPanel
            open={shownPanel === "simulation"}
            onClose={() => setLeftPanel("none")}
            baseConfig={config}
            liveState={liveState}
            onGenerateReport={setReport}
          />
          <OperationsConsole
            open={shownPanel === "operations"}
            onClose={() => setLeftPanel("none")}
            liveState={liveState}
            anomalyScore={anomalyScore}
            latestAnomaly={latestAnomaly}
            events={events}
            onOpenSimulationLab={() => setLeftPanel("simulation")}
            onGenerateReport={setReport}
          />
          <IncidentsPanel
            open={shownPanel === "incidents"}
            onClose={() => setLeftPanel("none")}
            onFocusFacility={handleFocusFacility}
            latestAnomaly={latestAnomaly}
            onGenerateReport={setReport}
          />
        </div>
        <div className="flex-1 min-w-0 relative">
          <SceneErrorBoundary>
            <TwinScene
              selectedRackId={selectedRackId}
              onSelectRack={handleSelectRack}
              onDeselect={handleDeselect}
              onRequestFocus={handleRequestFocus}
              focusRequest={focusRequest}
              mode={mode}
              liveState={liveState}
            />
          </SceneErrorBoundary>
          <ModeLegend mode={mode} liveState={liveState} onGenerateReport={setReport} />
        </div>
        <SidePanel selectedRackId={selectedRackId} onDeselect={handleDeselect} liveState={liveState} />
      </div>
      <CommandPalette
        open={searchOpen}
        onOpenChange={setSearchOpen}
        onFocusRack={handleRequestFocus}
        onFocusZone={handleFocusZone}
        onSelectAlert={() => setLeftPanel("incidents")}
        events={events}
      />
      <ReportDialog report={report} onClose={() => setReport(null)} />
    </div>
  );
}
