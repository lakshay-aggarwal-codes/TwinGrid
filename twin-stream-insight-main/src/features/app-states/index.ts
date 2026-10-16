import type { FeatureModule } from "../types";
import StatusBarSlotWidget from "./SlotWidget";

/**
 * Task 20: the persistent status bar. `StandardState`, `StandardBoundary` and `StateSkeleton` (exported from this folder)
 * are the shared empty/loading/error/stale components; a screen imports them from "@/features/app-states/StandardState".
 */
const feature: FeatureModule = {
  id: "app-states",
  slots: [{ slot: "settings", component: StatusBarSlotWidget, order: 1 }],
};
export default feature;
