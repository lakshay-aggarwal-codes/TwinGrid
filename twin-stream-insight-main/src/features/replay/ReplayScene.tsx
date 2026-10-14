import { lazy, Suspense, useState } from "react";
import { SceneErrorBoundary } from "@/three/SceneErrorBoundary";
import { MEASURANDS } from "@/telemetry/history/model";
import type { LiveFeed } from "@/three/visualizationModes";
import { clockUtc, formatReading } from "./format";
import { isReplaying } from "./model";
import { useReplay } from "./ReplayContext";

const TwinScene = lazy(() => import("@/three/TwinScene").then((m) => ({ default: m.TwinScene })));

/**
 * The 3D view never receives a live frame here. Stored history holds five facility-wide measurands (no per-rack,
 * inlet-temperature, PUE or cooling-mode data), so the racks stay in the neutral "physical" colouring and the replayed
 * values are listed beside the scene. Nothing is tinted from data the store does not hold.
 */
const NO_FRAME: LiveFeed = { frame: null, freshness: { state: "connecting", ageMs: null, staleAfterMs: 0, lastReceivedAt: null } };

export function ReplayScene() {
  const { state, snapshot } = useReplay();
  const [shown, setShown] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const replaying = isReplaying(state);

  return (
    <section aria-label="3D facility view during replay" className="space-y-2 rounded-md border border-border bg-card p-3" data-testid="replay-scene">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">3D facility view</h2>
        <button type="button" aria-pressed={shown} onClick={() => setShown((s) => !s)} className="rounded border border-border bg-background px-2 py-1 text-xs hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {shown ? "Hide 3D view" : "Show 3D view"}
        </button>
      </div>
      <p className="text-xs text-muted-foreground">
        {replaying ? "REPLAY — not live. " : ""}Racks are not tinted: stored history has five facility-wide measurands and no per-rack or thermal-inlet values.
      </p>
      <div className="grid gap-3 md:grid-cols-[1fr_14rem]">
        {shown ? (
          <div className="relative h-72 min-w-0 overflow-hidden rounded border border-border">
            <SceneErrorBoundary>
              <Suspense fallback={<p role="status" className="p-3 text-xs text-muted-foreground">Loading 3D view…</p>}>
                <TwinScene selectedRackId={selected} onSelectRack={setSelected} onDeselect={() => setSelected(null)} onRequestFocus={setSelected} focusRequest={null} mode="physical" feed={NO_FRAME} />
              </Suspense>
            </SceneErrorBoundary>
          </div>
        ) : (
          <p className="rounded border border-dashed border-border p-3 text-xs text-muted-foreground">3D view hidden.</p>
        )}
        <dl className="space-y-1 text-xs" data-testid="replay-scene-readouts">
          {MEASURANDS.map((m) => {
            const r = snapshot?.[m.id];
            return (
              <div key={m.id} className="flex justify-between gap-2 border-b border-border/60 pb-1">
                <dt className="text-muted-foreground">{m.label}</dt>
                <dd className="tabular-nums text-foreground">{replaying && r?.kind === "value" ? `${formatReading(m.id, r.value)} · ${clockUtc(r.atMs)}` : replaying ? "no data" : "—"}</dd>
              </div>
            );
          })}
        </dl>
      </div>
    </section>
  );
}
