import type { SlotWidgetProps } from "../types";
import { TourHost } from "./TourHost";

/** The `settings`-slot entry: the host with its production defaults. */
export default function TourSlotWidget(_props: SlotWidgetProps) {
  return <TourHost />;
}
