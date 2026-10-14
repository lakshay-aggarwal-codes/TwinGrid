import type { FeatureModule } from "../types";
import CommandPaletteWidget from "./CommandPaletteHost";

/**
 * Task 12: the Ctrl/Cmd+K command palette and the `?` shortcuts dialog. It lives in the `settings` slot because the
 * account bar is the one place mounted on every route; features add rows by registering commands (FeatureModule.commands).
 */
const feature: FeatureModule = {
  id: "command-palette",
  slots: [{ slot: "settings", component: CommandPaletteWidget, order: 0 }],
};
export default feature;
