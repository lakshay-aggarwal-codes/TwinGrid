import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Clock, Database, History, Loader2, ServerOff, Wifi, WifiOff, type LucideIcon } from "lucide-react";
import { useFeed, shallowEqual } from "@/telemetry/useFeed";
import { useActiveFeedStore } from "@/telemetry/activeFeed";
import { monotonicClock, type Clock as FeedClock } from "@/telemetry/freshness";
import type { FeedStore } from "@/telemetry/feedStore";
import { backfillLine } from "../realtime-resilience/backfillText";
import { useBackfillState } from "../realtime-resilience/backfillState";
import { connectionView, lastUpdateText, originChip, type ConnectionIcon } from "./statusModel";

const ICON: Record<ConnectionIcon, LucideIcon> = { live: Wifi, connecting: Loader2, stale: Clock, offline: WifiOff, unavailable: ServerOff };

/** How often the age is recomputed between frames. */
const AGE_REFRESH_MS = 1000;

const select = (v: ReturnType<FeedStore["getView"]>) => ({
  state: v.freshness.state,
  receivedAt: v.receivedAtMonotonic,
  hasFrame: v.frame !== null,
  origin: v.frame?.provenance.origin,
});

function Bar({ store, clock }: { store: FeedStore; clock: FeedClock }) {
  const feed = useFeed(select, shallowEqual, store);
  const [now, setNow] = useState(() => clock.now());
  useEffect(() => {
    setNow(clock.now());
    const id = setInterval(() => setNow(clock.now()), AGE_REFRESH_MS);
    return () => clearInterval(id);
  }, [clock, feed.receivedAt]);

  const conn = connectionView(feed.state);
  const Icon = ICON[conn.icon];
  const origin = originChip(feed.hasFrame, feed.origin);
  const backfill = backfillLine(useBackfillState()); // Task 23: only present after a gap

  const bar = (
    <div
      role="group"
      aria-label="Connection status"
      data-testid="status-bar"
      className="pointer-events-none fixed bottom-11 left-2 z-40 flex max-w-[calc(100vw-1rem)] flex-wrap items-center gap-x-3 gap-y-0.5 rounded-md border border-border bg-card/85 px-2.5 py-1 text-xs text-muted-foreground backdrop-blur-sm sm:bottom-2"
    >
      <span data-testid="status-connection" data-state={conn.state} className="inline-flex items-center gap-1 font-medium text-foreground">
        <Icon aria-hidden="true" className={`h-3.5 w-3.5 ${conn.icon === "connecting" ? "animate-spin motion-reduce:animate-none" : ""}`} />
        {conn.label}
      </span>
      <span data-testid="status-age" className="inline-flex items-center gap-1">
        <Clock aria-hidden="true" className="h-3.5 w-3.5" />
        {lastUpdateText(feed.receivedAt, now)}
      </span>
      <span data-testid="status-origin" data-origin={origin.state ?? "none"} className="inline-flex items-center gap-1">
        <Database aria-hidden="true" className="h-3.5 w-3.5" />
        {origin.text}
      </span>
      {backfill && (
        <span data-testid="status-backfill" data-state={backfill.state} role="status" className="inline-flex items-center gap-1">
          <History aria-hidden="true" className="h-3.5 w-3.5" />
          {backfill.text}
        </span>
      )}
      {/* One live region that changes only when the connection state changes, so assistive tech hears transitions, not ticks. */}
      <span className="sr-only" role="status" aria-live={conn.assertive ? "assertive" : "polite"} data-testid="status-announcement">
        Connection: {conn.label}
      </span>
    </div>
  );
  return createPortal(bar, document.body);
}

/**
 * Task 20: the persistent status bar (connection, last update age, data origin). Mounted from the `settings` slot, so it
 * is on every signed-in page, and rendered into <body> so no page layout can clip or move it. Renders nothing until the
 * app's feed exists (signed out). `clock` is for tests.
 */
export function StatusBar({ clock = monotonicClock }: { clock?: FeedClock }) {
  const store = useActiveFeedStore();
  return store ? <Bar store={store} clock={clock} /> : null;
}
