import type { FeatureModule } from "../types";
import { requestTour } from "./requests";
import TourSlotWidget from "./SlotWidget";

/**
 * Task 20: first-run welcome and the 3-minute Story Mode. It has no page of its own: the host lives in the `settings`
 * slot (the account bar is on every signed-in route) and is started from the command palette.
 */
const feature: FeatureModule = {
  id: "guided-tour",
  slots: [{ slot: "settings", component: TourSlotWidget, order: 5 }],
  commands: [
    {
      id: "tour.start",
      label: "Start Story Mode (3-minute tour)",
      group: "Help",
      keywords: ["tour", "walkthrough", "guide", "demo", "story", "onboarding", "help"],
      run: () => requestTour("start"),
    },
    {
      id: "tour.resume",
      label: "Resume Story Mode",
      group: "Help",
      keywords: ["tour", "continue", "resume", "story"],
      run: () => requestTour("resume"),
    },
    {
      id: "tour.welcome",
      label: "Show the welcome screen",
      group: "Help",
      keywords: ["welcome", "intro", "getting started", "onboarding"],
      run: () => requestTour("welcome"),
    },
  ],
};
export default feature;
