import type { SlotWidgetProps } from "../types";
import { StatusBar } from "./StatusBar";

/** The `settings`-slot entry: the status bar with its production defaults. */
export default function StatusBarSlotWidget(_props: SlotWidgetProps) {
  return <StatusBar />;
}
