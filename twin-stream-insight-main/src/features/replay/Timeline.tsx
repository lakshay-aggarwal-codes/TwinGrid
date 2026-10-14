import { useRef, type KeyboardEvent, type PointerEvent } from "react";
import { fullUtc } from "./format";
import { fractionOf, isReplaying, msAtFraction, scrubKeyTarget } from "./model";
import { shapeFor, type AlertPin, type PinShape } from "./pins";
import { useReplay } from "./ReplayContext";

function PinGlyph({ shape, filled }: { shape: PinShape; filled: boolean }) {
  const common = { fill: filled ? "currentColor" : "none", stroke: "currentColor", strokeWidth: 2 };
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
      {shape === "triangle" ? <path d="M7 1.5 13 12.5H1Z" {...common} /> : shape === "diamond" ? <path d="M7 1 13 7 7 13 1 7Z" {...common} /> : <circle cx="7" cy="7" r="5" {...common} />}
    </svg>
  );
}

const SHAPE_WORD: Record<PinShape, string> = { triangle: "critical (triangle)", diamond: "warning (diamond)", circle: "info (circle)" };

/**
 * The scrubber: a slider over the requested window, with an alert pin per stored alert (shape + label, filled = not yet
 * acknowledged), the compare time B, and the window ends. Keyboard: arrows / Page / Home / End. Pointer: press and drag.
 */
export function Timeline() {
  const { state, dispatch, alerts } = useReplay();
  const track = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const replaying = isReplaying(state);
  const cursor = state.cursorMs ?? state.toMs;

  const msFromPointer = (e: PointerEvent<HTMLElement>): number | null => {
    const el = track.current;
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return r.width <= 0 ? null : msAtFraction((e.clientX - r.left) / r.width, state.fromMs, state.toMs);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const target = scrubKeyTarget(e.key, cursor, state.fromMs, state.toMs);
    if (target === null) return;
    e.preventDefault();
    dispatch({ type: "scrub", ms: target });
  };

  return (
    <div className="space-y-1" data-testid="replay-timeline">
      <div
        ref={track}
        className="relative h-12 touch-none select-none"
        onPointerDown={(e) => {
          const ms = msFromPointer(e);
          if (ms === null) return;
          dragging.current = true;
          e.currentTarget.setPointerCapture?.(e.pointerId);
          dispatch({ type: "scrub", ms });
        }}
        onPointerMove={(e) => {
          if (!dragging.current) return;
          const ms = msFromPointer(e);
          if (ms !== null) dispatch({ type: "scrub", ms });
        }}
        onPointerUp={() => {
          dragging.current = false;
        }}
        onPointerCancel={() => {
          dragging.current = false;
        }}
      >
        <div className="absolute inset-x-0 top-6 h-2 rounded bg-muted" aria-hidden="true" />
        {replaying && <div className="absolute left-0 top-6 h-2 rounded-l bg-primary/50" style={{ width: `${fractionOf(cursor, state.fromMs, state.toMs) * 100}%` }} aria-hidden="true" />}

        {alerts.pins.map((p: AlertPin) => (
          <button
            key={p.id}
            type="button"
            data-testid="replay-pin"
            aria-label={`Alert ${p.id}, ${SHAPE_WORD[shapeFor(p.severity)]}, ${p.acknowledged ? "acknowledged" : "not acknowledged"}, ${fullUtc(p.ms)}. Jump to this time.`}
            title={`${p.label} — ${fullUtc(p.ms)}`}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={() => dispatch({ type: "scrub", ms: p.ms })}
            className="absolute top-0 -translate-x-1/2 rounded p-0.5 text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            style={{ left: `${p.fraction * 100}%` }}
          >
            <PinGlyph shape={p.shape} filled={!p.acknowledged} />
          </button>
        ))}

        {state.compareOn && state.compareBMs !== null && (
          <div
            data-testid="replay-marker-b"
            className="absolute top-4 h-6 -translate-x-1/2 border-l-2 border-dashed border-foreground"
            style={{ left: `${fractionOf(state.compareBMs, state.fromMs, state.toMs) * 100}%` }}
            title={`Compare time B: ${fullUtc(state.compareBMs)}`}
          >
            <span className="absolute -top-3 left-1 text-[10px] font-semibold">B</span>
          </div>
        )}

        <div
          role="slider"
          tabIndex={0}
          aria-label="Replay time (UTC)"
          aria-valuemin={state.fromMs}
          aria-valuemax={state.toMs}
          aria-valuenow={cursor}
          aria-valuetext={replaying ? fullUtc(cursor) : "Live"}
          onKeyDown={onKeyDown}
          onPointerDown={(e) => e.stopPropagation()}
          className="absolute top-4 h-6 w-4 -translate-x-1/2 cursor-grab rounded border-2 border-background bg-primary shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          style={{ left: `${fractionOf(cursor, state.fromMs, state.toMs) * 100}%` }}
        />
      </div>
      <div className="flex justify-between text-[11px] text-muted-foreground">
        <span>{fullUtc(state.fromMs)}</span>
        <span>{fullUtc(state.toMs)}</span>
      </div>
      {alerts.status === "error" && <p className="text-[11px] text-muted-foreground">Alert pins could not be loaded.</p>}
      {alerts.status === "ready" && alerts.mayBeIncomplete && (
        <p className="text-[11px] text-muted-foreground">Pins come from the latest 200 stored alerts; older alerts in this window may not be shown.</p>
      )}
      {alerts.status === "ready" && alerts.skipped > 0 && <p className="text-[11px] text-muted-foreground">{alerts.skipped} alert(s) had no readable time and are not pinned.</p>}
    </div>
  );
}
