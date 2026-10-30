import type { TourStep } from "./engine";

const PAGE_HEADING = ["h1", "main"] as const;

/**
 * Story Mode: about three minutes for an operator (180 s of captions), less for a viewer (operator-only steps are left out).
 * Wording rule: everything is about a SIMULATION. No step calls anything measured, validated, calibrated or optimal;
 * `steps.test.ts` scans every caption for those words.
 */
export const STORY_STEPS: readonly TourStep[] = [
  {
    id: "welcome",
    route: "/",
    targets: ["h1"],
    title: "Welcome to TwinGrid",
    caption: "TwinGrid is a simulation-based digital twin of a data centre. Every value you see is produced by a simulator, not by a live facility.",
    durationMs: 14000,
  },
  {
    id: "status",
    route: "/",
    targets: ['[data-testid="liveness"]', '[data-testid="origin-banner"]'],
    title: "Live status and data origin",
    caption: "Here you can see whether the feed is live, stale or disconnected, and where the numbers come from. The origin reads Simulated when the backend says so.",
    durationMs: 14000,
  },
  {
    id: "facility",
    route: "/",
    targets: ['[aria-label^="3D facility view"]'],
    title: "The 3D facility",
    caption: "Click a rack, or use the arrow keys, to select it; the side panel shows its readings. Enter zooms to the selected rack and Escape clears it.",
    durationMs: 16000,
  },
  {
    id: "modes",
    route: "/",
    targets: ['[aria-label="Visualization mode"]'],
    title: "Visualization modes",
    caption: "Switch the visualization mode to change what the scene emphasises. A legend explains the colours, and every colour also has a text readout.",
    durationMs: 12000,
  },
  {
    id: "dashboard",
    route: "/analytics",
    targets: ['[data-slot="dashboard"]', ...PAGE_HEADING],
    title: "Executive dashboard",
    caption: "Headline numbers, goal rings and plain-language insights for the running simulation, all labelled as simulated.",
    durationMs: 14000,
  },
  {
    id: "replay",
    route: "/replay",
    targets: PAGE_HEADING,
    title: "Replay and time travel",
    caption: "Step back through stored history and compare moments in time. Replayed data is labelled as replayed, never as live.",
    durationMs: 16000,
  },
  {
    id: "whatif",
    route: "/whatif-lab",
    targets: PAGE_HEADING,
    title: "What-if lab",
    caption: "Here the simulated outcome is shown against the baseline, from model estimates on simulated data. Operators and admins can change the inputs; for a viewer they are locked, because the app is read-only for viewers.",
    durationMs: 16000,
  },
  {
    id: "alerts",
    route: "/alerts",
    targets: PAGE_HEADING,
    title: "Alerts centre",
    caption: "Alerts raised during the simulation, with filters, a timeline and a plain-language explanation of what triggered each one.",
    durationMs: 16000,
  },
  {
    id: "alerts-operator",
    route: "/alerts",
    targets: PAGE_HEADING,
    title: "Your operator tools",
    caption: "As an operator you can acknowledge and work through alerts. Viewers can read them but not change them.",
    durationMs: 12000,
    minRole: "operator",
  },
  {
    id: "optimizer",
    route: "/optimizer",
    targets: PAGE_HEADING,
    title: "Optimizer and approvals",
    caption: "A recommendation from the best usable baseline controller, with its predicted effect on simulated scenarios. An approval is a recorded decision; it does not change the simulation.",
    durationMs: 14000,
  },
  {
    id: "optimizer-operator",
    route: "/optimizer",
    targets: PAGE_HEADING,
    title: "Propose a set-point",
    caption: "Operators can propose a set-point. Only an admin can approve or reject a proposal, and never their own.",
    durationMs: 12000,
    minRole: "operator",
  },
  {
    id: "palette",
    route: "/",
    title: "Jump anywhere",
    caption: "Press Ctrl+K (⌘K on a Mac) to open the command palette and go to any page or scenario. Press ? for the list of shortcuts.",
    durationMs: 12000,
  },
  {
    id: "passport",
    route: "/",
    title: "Know the models",
    caption: "Open the Model Passport from the command palette to see what each model is and the limitations it states. You can restart this tour from the same palette.",
    durationMs: 12000,
  },
];
