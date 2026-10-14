import { useState } from "react";
import { GitCompare, Link2, Pause, Play, RefreshCw, Radio, SkipBack, SkipForward } from "lucide-react";
import { SPEEDS, WINDOW_HOURS, isReplaying } from "./model";
import { neighbourPin } from "./pins";
import { useReplay } from "./ReplayContext";

const btn =
  "inline-flex items-center gap-1.5 rounded border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** Play/pause, 1x-60x, LIVE, previous/next alert, window, compare and share. Every control is a real button or select. */
export function Transport() {
  const { state, dispatch, hours, setHours, alerts, refreshWindow, shareUrl } = useReplay();
  const [copied, setCopied] = useState<"idle" | "copied" | "failed">("idle");
  const playing = state.mode === "playing";
  const replaying = isReplaying(state);
  const here = state.cursorMs ?? state.toMs;
  const prev = neighbourPin(alerts.pins, here, -1);
  const next = neighbourPin(alerts.pins, here, 1);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl());
      setCopied("copied");
    } catch {
      setCopied("failed");
    }
    setTimeout(() => setCopied("idle"), 3000);
  };

  return (
    <div className="space-y-3" data-testid="replay-transport">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={btn} onClick={() => dispatch({ type: "toggle" })} aria-pressed={playing}>
          {playing ? <Pause aria-hidden="true" className="h-3.5 w-3.5" /> : <Play aria-hidden="true" className="h-3.5 w-3.5" />}
          {playing ? "Pause" : "Play"}
        </button>
        <button type="button" className={btn} onClick={() => dispatch({ type: "live" })} disabled={!replaying} aria-label="Return to LIVE">
          <Radio aria-hidden="true" className="h-3.5 w-3.5" />
          LIVE
        </button>
        <button type="button" className={btn} disabled={!prev} onClick={() => prev && dispatch({ type: "scrub", ms: prev.ms })} aria-label="Previous alert">
          <SkipBack aria-hidden="true" className="h-3.5 w-3.5" />
          Alert
        </button>
        <button type="button" className={btn} disabled={!next} onClick={() => next && dispatch({ type: "scrub", ms: next.ms })} aria-label="Next alert">
          Alert
          <SkipForward aria-hidden="true" className="h-3.5 w-3.5" />
        </button>

        <div role="radiogroup" aria-label="Replay speed" className="inline-flex overflow-hidden rounded border border-border">
          {SPEEDS.map((s) => (
            <button
              key={s}
              type="button"
              role="radio"
              aria-checked={state.speed === s}
              onClick={() => dispatch({ type: "speed", speed: s })}
              className={`px-2 py-1 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring ${state.speed === s ? "bg-primary text-primary-foreground font-semibold underline" : "bg-background text-foreground hover:bg-muted"}`}
            >
              {s}×
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Window
          <select className="rounded border border-border bg-background px-2 py-1 text-xs text-foreground" value={hours} onChange={(e) => setHours(Number(e.target.value))}>
            {WINDOW_HOURS.map((h) => (
              <option key={h} value={h}>
                {h === 168 ? "168 h (backend maximum)" : `${h} h`}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className={btn} onClick={refreshWindow}>
          <RefreshCw aria-hidden="true" className="h-3.5 w-3.5" />
          Refresh window
        </button>
        <label className="flex items-center gap-2 text-xs text-foreground">
          <input type="checkbox" checked={state.compareOn} onChange={(e) => dispatch({ type: "compare", on: e.target.checked })} className="h-4 w-4" />
          <GitCompare aria-hidden="true" className="h-3.5 w-3.5" />
          Compare two times
        </label>
        {state.compareOn && (
          <button type="button" className={btn} disabled={!replaying} onClick={() => dispatch({ type: "setB", ms: state.cursorMs })}>
            Set B to this time
          </button>
        )}
        <button type="button" className={btn} onClick={copy} disabled={!replaying}>
          <Link2 aria-hidden="true" className="h-3.5 w-3.5" />
          Copy link
        </button>
        <span role="status" className="text-xs text-muted-foreground">
          {copied === "copied" ? "Link copied." : copied === "failed" ? "Could not copy; copy the address bar instead." : ""}
        </span>
      </div>
    </div>
  );
}
