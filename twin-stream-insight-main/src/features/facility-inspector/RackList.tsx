import { useCallback, useMemo, useRef, useState } from "react";
import type { SlotWidgetProps } from "../types";
import { inspectorBridge } from "@/three/inspectorBridge";
import { useTopology } from "@/three/facilityTopology";
import { describeRack } from "@/three/rackNavigation";
import { isListKey, listOrder, moveInList } from "./selectionUrl";

/**
 * Slot widget (`facility-inspector`): every rack as a list, the keyboard/screen-reader alternative to the canvas.
 * One tab stop (roving tabindex); arrows, Home and End move focus, Enter or Space selects and flies to the rack.
 */
export default function RackList({ context }: SlotWidgetProps) {
  const { layout } = useTopology();
  const selectedId = typeof context.rackId === "string" ? context.rackId : null;
  const order = useMemo(() => listOrder(layout), [layout]);
  const [focusId, setFocusId] = useState<string | null>(null);
  const refs = useRef(new Map<string, HTMLButtonElement>());

  const tabStop = focusId !== null && order.includes(focusId) ? focusId : selectedId !== null && order.includes(selectedId) ? selectedId : (order[0] ?? null);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLUListElement>) => {
      if (!isListKey(event.key) || event.ctrlKey || event.metaKey || event.altKey) return;
      event.preventDefault();
      const next = moveInList(order, tabStop, event.key);
      if (next === null) return;
      setFocusId(next);
      refs.current.get(next)?.focus();
    },
    [order, tabStop],
  );

  if (order.length === 0) return <p className="text-xs text-muted-foreground">No racks to list.</p>;

  return (
    <section aria-label="Rack list" data-testid="rack-list" className="space-y-1.5">
      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Racks ({order.length})</p>
      <p className="text-[11px] text-muted-foreground">Arrow keys move, Enter selects and zooms. Same racks as the 3D view.</p>
      <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
        {layout.zones.map((zone) => {
          const racks = layout.racks.filter((r) => r.zoneId === zone.zoneId);
          if (racks.length === 0) return null;
          return (
            <div key={zone.zoneId}>
              <p className="text-[11px] font-medium text-foreground">{zone.label}</p>
              <ul className="mt-0.5 space-y-0.5" onKeyDown={onKeyDown} aria-label={`${zone.label} racks`}>
                {racks.map((r) => {
                  const selected = r.rackId === selectedId;
                  return (
                    <li key={r.rackId}>
                      <button
                        type="button"
                        ref={(el) => {
                          if (el) refs.current.set(r.rackId, el);
                          else refs.current.delete(r.rackId);
                        }}
                        tabIndex={r.rackId === tabStop ? 0 : -1}
                        aria-current={selected ? "true" : undefined}
                        onFocus={() => setFocusId(r.rackId)}
                        onClick={() => inspectorBridge.actions.selectRack(r.rackId)}
                        data-testid={`rack-item-${r.rackId}`}
                        className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${selected ? "bg-muted font-semibold text-foreground" : "text-muted-foreground"}`}
                      >
                        <span aria-hidden="true" className="w-3 font-mono">
                          {selected ? "▶" : ""}
                        </span>
                        <span>{describeRack(r.rackId, layout)}</span>
                        {selected && <span className="sr-only"> (selected)</span>}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </div>
    </section>
  );
}
