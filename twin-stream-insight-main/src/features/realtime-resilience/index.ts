import type { FeatureModule } from "../types";
import BackfillHost from "./BackfillHost";

/**
 * Task 23: realtime resilience. The connection state machine is the feed store's (`telemetry/feedStore.ts`,
 * `telemetry/freshness.ts`); this feature adds the gap backfill from the history API after a reconnect. Reconnect
 * jitter lives in `api/wsTransport.ts`; the hidden-tab render pause in `three/TwinScene.tsx`.
 */
const feature: FeatureModule = {
  id: "realtime-resilience",
  slots: [{ slot: "settings", component: BackfillHost, order: 2 }],
};
export default feature;
