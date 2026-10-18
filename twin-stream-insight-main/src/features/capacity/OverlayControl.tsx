import { useEffect } from "react";
import { Link } from "react-router-dom";
import { Boxes } from "lucide-react";
import type { SlotWidgetProps } from "../types";
import { useSharedSimulation } from "@/hooks/simulationContext";
import { StateBoundary } from "@/state/StateBoundary";
import { STATUS_STYLE, headroomOverlay, useHeadroomOverlay, type HeadroomStatus } from "@/three/headroomOverlayStore";
import { ESTIMATE_LABEL, overlayPatch } from "./model";
import { usePlan } from "./planStore";
import { useCapacity } from "./useCapacity";

const BUTTON =
  "inline-flex items-center gap-1.5 rounded border border-border px-2 py-1 text-xs text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const STATUSES: readonly HeadroomStatus[] = ["ok", "tight", "exceeded"];
const MEANING: Record<HeadroomStatus, string> = {
  ok: "ok · at least the planning margin free",
  tight: "tight · inside the planning margin",
  exceeded: "exceeded · a limit is passed",
};

/**
 * Slot `facility-inspector`: the headroom overlay switch. Off: nothing is fetched and nothing is drawn. On: the plan from
 * the Capacity page is evaluated (debounced, rate limited) and every zone is tinted with the plan's worst status.
 */
export default function OverlayControl(_props: SlotWidgetProps) {
  const { config } = useSharedSimulation();
  const plan = usePlan();
  const overlay = useHeadroomOverlay();
  const on = overlay.enabled;
  const { state, refetch } = useCapacity(config, plan, on);

  const data = state.status === "ready" ? state.data : null;
  useEffect(() => {
    headroomOverlay.publish(overlayPatch(on ? data : null));
  }, [on, data]);
  // Leaving the Live Twin removes the overlay's state; coming back starts with it off.
  useEffect(() => () => headroomOverlay.reset(), []);

  return (
    <section aria-label="Headroom overlay" data-testid="headroom-control" className="space-y-1.5">
      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Capacity</p>
      <button
        type="button"
        aria-pressed={on}
        className={`${BUTTON} ${on ? "border-primary bg-muted font-medium" : ""}`}
        onClick={() => headroomOverlay.publish({ enabled: !on })}
        data-testid="headroom-toggle"
      >
        <Boxes aria-hidden="true" className="h-3.5 w-3.5" />
        Headroom overlay
        {on && <span className="sr-only"> (on)</span>}
      </button>
      {on && (
        <div data-testid="headroom-legend" className="space-y-1">
          <StateBoundary state={state} onRetry={refetch} messages={{ loading: "Estimating headroom…" }}>
            {(c) => (
              <p className="text-[11px] text-foreground" data-testid="headroom-summary">
                {c.plan.add_racks === 0 ? "Current headroom" : `+${c.plan.add_racks} racks at ${c.plan.kw_per_rack} kW`}: {STATUS_STYLE[c.with_plan.overall].word}.
              </p>
            )}
          </StateBoundary>
          <ul className="space-y-0.5 text-[11px]">
            {STATUSES.map((s) => (
              <li key={s} className={`flex items-center gap-1.5 ${overlay.status === s ? "font-semibold text-foreground" : "text-muted-foreground"}`} data-active={overlay.status === s ? "true" : undefined}>
                <span aria-hidden="true" className="w-3 text-center font-mono">{STATUS_STYLE[s].glyph}</span>
                <span>{MEANING[s]}</span>
              </li>
            ))}
          </ul>
          <p className="text-[11px] text-muted-foreground">
            {ESTIMATE_LABEL} on simulated data. Facility headroom shown as an even share per zone: the model has no per-zone limits.{" "}
            <Link to="/capacity" className="underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Change the plan</Link>
          </p>
        </div>
      )}
    </section>
  );
}
