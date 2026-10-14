import { Leaf, Thermometer, Wind, Zap, type LucideIcon } from "lucide-react";
import { useMemo } from "react";
import type { SlotWidgetProps } from "../types";
import { useFeed } from "@/telemetry/useFeed";
import { CAMERA_PRESETS } from "@/three/cameraPresets";
import { inspectorBridge, useInspectorBridge } from "@/three/inspectorBridge";
import { currentState } from "@/three/visualizationModes";
import { LAYERS, layerForMode, legendFor, modeAfterToggle, type LayerId } from "./layers";

const ICONS: Record<LayerId, LucideIcon> = { thermal: Thermometer, airflow: Wind, power: Zap, carbon: Leaf };

const BUTTON =
  "inline-flex items-center gap-1.5 rounded border border-border px-2 py-1 text-xs text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** Slot widget (`facility-inspector`): camera presets, layer toggles and the legend for the active layer. */
export default function ViewControls(_props: SlotWidgetProps) {
  const mode = useInspectorBridge((s) => s.mode);
  const active = layerForMode(mode);
  const frame = useFeed((v) => v.frame);
  const freshness = useFeed((v) => v.freshness);
  // Only a CURRENT frame marks a band as the current one; stale or missing data marks nothing.
  const live = useMemo(() => currentState({ frame, freshness }), [frame, freshness]);
  const legend = active
    ? legendFor(active, live ? { pue: live.pue, wue: live.wue, coolingMode: live.cooling_mode, inletTempC: live.server_inlet_temp_C, outletTempC: live.server_outlet_temp_C } : null)
    : [];
  const def = LAYERS.find((l) => l.id === active);

  return (
    <section aria-label="Facility view controls" data-testid="view-controls" className="space-y-3">
      <div className="space-y-1.5">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Camera</p>
        <div role="group" aria-label="Camera presets" className="flex flex-wrap gap-1.5">
          {CAMERA_PRESETS.map((p) => (
            <button key={p.id} type="button" className={BUTTON} onClick={() => inspectorBridge.actions.flyToPreset(p.id)} data-testid={`preset-${p.id}`}>
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-1.5">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Layers</p>
        <div role="group" aria-label="Scene layers" className="flex flex-wrap gap-1.5">
          {LAYERS.map((l) => {
            const Icon = ICONS[l.id];
            const on = active === l.id;
            return (
              <button
                key={l.id}
                type="button"
                aria-pressed={on}
                className={`${BUTTON} ${on ? "border-primary bg-muted font-medium" : ""}`}
                onClick={() => inspectorBridge.actions.setMode(modeAfterToggle(mode, l.id))}
                data-testid={`layer-${l.id}`}
              >
                <Icon aria-hidden="true" className="h-3.5 w-3.5" />
                {l.label}
                {on && <span className="sr-only"> (on)</span>}
              </button>
            );
          })}
        </div>
        <p className="text-[11px] text-muted-foreground">One layer at a time; turn it off to return to the plain view.</p>
      </div>

      {def && (
        <div data-testid="layer-legend" className="space-y-1">
          <p className="text-xs font-semibold text-foreground">{def.label} legend</p>
          <p className="text-[11px] text-muted-foreground">{def.note}</p>
          <ul className="space-y-0.5 text-[11px]">
            {legend.map((e) => (
              <li key={e.key} className={`flex items-center gap-1.5 ${e.active ? "font-semibold text-foreground" : "text-muted-foreground"}`} data-active={e.active ? "true" : undefined}>
                <span aria-hidden="true" className="w-3 text-center font-mono">
                  {e.glyph}
                </span>
                <span>{e.text}</span>
                {e.active && <span className="rounded border border-border px-1 text-[10px] uppercase">Current</span>}
              </li>
            ))}
          </ul>
          {!live && <p className="text-[11px] text-muted-foreground">No current reading: nothing is marked as current.</p>}
        </div>
      )}
    </section>
  );
}
