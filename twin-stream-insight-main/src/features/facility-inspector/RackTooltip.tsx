import { useCallback, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import type { SlotWidgetProps } from "../types";
import { useInspectorBridge } from "@/three/inspectorBridge";
import { useTopology } from "@/three/facilityTopology";
import { describeRack } from "@/three/rackNavigation";
import { tooltipPosition } from "./tooltipPosition";

/**
 * Slot widget (`facility-inspector`): the hover tooltip. It is a DOM element positioned straight from pointer events
 * (a ref and `style`, no React state per move), so hovering never re-renders the scene. It names the rack only: the
 * backend has no per-rack numbers, so the readings live in the inspector, labelled facility-wide.
 */
export default function RackTooltip(_props: SlotWidgetProps) {
  const hovered = useInspectorBridge((s) => s.hoveredRackId);
  const { layout } = useTopology();
  const pointer = useRef<{ x: number; y: number } | null>(null);
  const box = useRef<HTMLDivElement | null>(null);

  const place = useCallback(() => {
    const el = box.current;
    const p = pointer.current;
    if (!el || !p) return;
    const pos = tooltipPosition(p.x, p.y, { width: el.offsetWidth, height: el.offsetHeight }, { width: window.innerWidth, height: window.innerHeight });
    el.style.left = `${pos.left}px`;
    el.style.top = `${pos.top}px`;
    el.style.visibility = "visible";
  }, []);

  useEffect(() => {
    let frame = 0;
    const onMove = (event: PointerEvent) => {
      pointer.current = { x: event.clientX, y: event.clientY };
      if (frame === 0) {
        frame = window.requestAnimationFrame(() => {
          frame = 0;
          place();
        });
      }
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      if (frame !== 0) window.cancelAnimationFrame(frame);
    };
  }, [place]);

  useEffect(() => {
    if (hovered !== null) place();
  }, [hovered, place]);

  if (hovered === null) return null;
  return createPortal(
    <div
      ref={box}
      role="tooltip"
      aria-hidden="true"
      data-testid="rack-tooltip"
      style={{ position: "fixed", left: 0, top: 0, visibility: "hidden", pointerEvents: "none", zIndex: 60 }}
      className="max-w-[16rem] rounded border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-md"
    >
      <p className="font-medium">{describeRack(hovered, layout)}</p>
      <p className="text-[11px] text-muted-foreground">Click to inspect · double-click to fly to it</p>
    </div>,
    document.body,
  );
}
