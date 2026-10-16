import type { FeatureModule } from "../types";
import ThemeToggle from "./ThemeToggle";
import MobileBottomNavSlotWidget from "./MobileBottomNav";
import { applyTheme, readStoredTheme } from "./theme";

// Applied when the app's features load (before first render), so a saved light choice does not flash dark.
if (typeof document !== "undefined") applyTheme(readStoredTheme());

/**
 * Task 21: design polish. The dark/light switch (header actions) and the phone bottom navigation (settings slot).
 * Tokens live in src/index.css and tailwind.config.ts; the colour-blind-safe chart palette is chartPalette.ts.
 */
const feature: FeatureModule = {
  id: "design-polish",
  slots: [
    { slot: "header-actions", component: ThemeToggle, order: 90 },
    { slot: "settings", component: MobileBottomNavSlotWidget, order: 2 },
  ],
};
export default feature;
