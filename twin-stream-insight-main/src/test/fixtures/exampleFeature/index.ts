import { Beaker } from "lucide-react";
import { createElement, lazy } from "react";
import type { FeatureModule } from "@/features/types";

/** Example feature used ONLY by tests (it lives under src/test, so the registry's glob never ships it). */
const Page = lazy(() => Promise.resolve({ default: () => createElement("h1", null, "Example page") }));
const Widget = ({ context }: { context: Readonly<Record<string, unknown>> }) =>
  createElement("p", { "data-testid": "example-widget" }, `example widget rack=${String(context.rackId ?? "none")}`);

const example: FeatureModule = {
  id: "example",
  route: { path: "/example", component: Page },
  nav: { label: "Example", icon: Beaker, group: "Labs", order: 1 },
  commands: [{ id: "example.hello", label: "Say hello", group: "Example", run: () => undefined }],
  slots: [{ slot: "dashboard", component: Widget, order: 10 }, { slot: "facility-inspector", component: Widget, order: 10 }],
};
export default example;
