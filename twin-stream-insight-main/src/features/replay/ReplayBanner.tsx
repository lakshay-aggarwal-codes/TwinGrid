import { History, Radio } from "lucide-react";
import { useFeed } from "@/telemetry/useFeed";
import { fullUtc } from "./format";
import { isReplaying } from "./model";
import { useReplay } from "./ReplayContext";

/**
 * The persistent banner. Replaying: "REPLAY — not live" with the data time and a way back. Live: what the live feed
 * itself reports (never "live" on the strength of the page alone). The text, the icon and the dotted border all carry
 * the meaning, so it does not rely on colour. One `role="status"` region, so a change is announced once.
 */
export function ReplayBanner() {
  const { state, dispatch } = useReplay();
  const freshness = useFeed((v) => v.freshness);
  const replaying = isReplaying(state);

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="replay-banner"
      data-replaying={replaying ? "true" : "false"}
      className={`sticky top-0 z-20 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border-2 px-3 py-2 text-sm backdrop-blur ${
        replaying ? "border-dotted border-amber-500 bg-amber-500/15 text-foreground" : "border-solid border-border bg-card/90 text-muted-foreground"
      }`}
    >
      {replaying ? (
        <>
          <History aria-hidden="true" className="h-4 w-4 shrink-0" />
          <strong className="tracking-wide">REPLAY — not live</strong>
          <span>
            Stored simulated telemetry at <time dateTime={state.cursorMs === null ? undefined : new Date(state.cursorMs).toISOString()}>{state.cursorMs === null ? "—" : fullUtc(state.cursorMs)}</time>
          </span>
          <button
            type="button"
            onClick={() => dispatch({ type: "live" })}
            className="ml-auto rounded border border-border bg-background px-2 py-0.5 text-xs font-medium text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Return to LIVE
          </button>
        </>
      ) : (
        <>
          <Radio aria-hidden="true" className="h-4 w-4 shrink-0" />
          <strong>LIVE view</strong>
          <span data-testid="replay-live-state">Live feed: {freshness.state}. Move the time slider or press Play to replay stored telemetry.</span>
        </>
      )}
    </div>
  );
}
