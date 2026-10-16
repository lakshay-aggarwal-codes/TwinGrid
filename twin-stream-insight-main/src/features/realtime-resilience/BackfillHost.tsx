import { useEffect } from "react";
import { useActiveFeedStore } from "@/telemetry/activeFeed";
import type { SlotWidgetProps } from "../types";
import { createBackfiller } from "./backfill";
import { clearActiveBackfiller, setActiveBackfiller } from "./backfillState";

/**
 * Task 23: headless `settings`-slot widget. While a signed-in feed exists it runs one backfiller on it and publishes
 * its state for the status bar. Renders nothing itself.
 */
export default function BackfillHost(_props: SlotWidgetProps) {
  const feed = useActiveFeedStore();
  useEffect(() => {
    if (!feed) return;
    const backfiller = createBackfiller(feed);
    backfiller.start();
    setActiveBackfiller(backfiller);
    return () => {
      clearActiveBackfiller(backfiller);
      backfiller.stop();
    };
  }, [feed]);
  return null;
}
