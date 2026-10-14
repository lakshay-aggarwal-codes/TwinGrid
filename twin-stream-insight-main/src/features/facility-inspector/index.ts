import type { FeatureModule } from "../types";
import RackReadouts from "./RackReadouts";
import RackTooltip from "./RackTooltip";
import RackList from "./RackList";
import ViewControls from "./ViewControls";

/**
 * Task 13: the interactive facility inspector. Four widgets in the `facility-inspector` slot of the Live Twin's right
 * rail: readings for the selected rack (facility-wide values, labelled so), the view controls (camera presets, layers,
 * legend), the keyboard-accessible rack list, and the hover tooltip. The page wires selection through `useInspectorHost`.
 */
const feature: FeatureModule = {
  id: "facility-inspector",
  slots: [
    { slot: "facility-inspector", component: RackReadouts, order: 0 },
    { slot: "facility-inspector", component: ViewControls, order: 10 },
    { slot: "facility-inspector", component: RackList, order: 20 },
    { slot: "facility-inspector", component: RackTooltip, order: 30 },
  ],
};
export default feature;
