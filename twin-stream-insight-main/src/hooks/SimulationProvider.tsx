import { useEffect, useState, type ReactNode } from "react";
import { useSimulation } from "@/hooks/useSimulation";
import { createFeedStore } from "@/telemetry/feedStore";
import { FeedStoreContext } from "@/telemetry/useFeed";
import { SimulationContext } from "./simulationContext.ts";

/**
 * Stage 16: owns the one and only `useSimulation()` instance (one WebSocket, one anomaly buffer, one set of
 * slider values). Mounted above <Routes>, so it survives page changes.
 *
 * FE-04: also owns the one telemetry feed store. The socket is opened here (and closed on unmount, e.g. sign-out)
 * rather than inside `useSimulation`; components read the feed with `useFeed(selector)`.
 */
export function SimulationProvider({ children }: { children: ReactNode }) {
  const [feed] = useState(() => createFeedStore());
  useEffect(() => {
    feed.start();
    return () => feed.stop();
  }, [feed]);

  const value = useSimulation(feed);
  return (
    <FeedStoreContext.Provider value={feed}>
      <SimulationContext.Provider value={value}>{children}</SimulationContext.Provider>
    </FeedStoreContext.Provider>
  );
}
