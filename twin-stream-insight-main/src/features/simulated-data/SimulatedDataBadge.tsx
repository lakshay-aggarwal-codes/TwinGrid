import { useContext } from "react";
import { FeedStoreContext, useFeed } from "@/telemetry/useFeed";
import type { FeedStore, FeedView } from "@/telemetry/feedStore";
import { classifyOrigin } from "@/provenance/model";
import { ORIGIN_BORDER } from "@/provenance/icons";
import { Pill } from "@/provenance/parts";
import { isSimulatedOrigin } from "./badgeState";

/**
 * Compact "Simulated data" marker for the header. Icon (flask) + dashed border + the words, so colour is never the
 * only cue. Renders nothing unless `origin` is exactly the backend value "simulated".
 */
export function SimulatedDataBadge({ origin }: { origin: string | null | undefined }) {
  if (!isSimulatedOrigin(origin)) return null;
  const view = classifyOrigin(origin);
  return (
    <span data-testid="simulated-data-badge">
      <Pill icon={view.icon} className={ORIGIN_BORDER.simulated} title={view.tooltip} data={{ "data-origin": "simulated" }}>
        Simulated data
      </Pill>
    </span>
  );
}

const selectOrigin = (v: FeedView): string | undefined => v.frame?.provenance.origin;

function Connected({ store }: { store: FeedStore }) {
  const origin = useFeed(selectOrigin, Object.is, store);
  return <SimulatedDataBadge origin={origin} />;
}

/**
 * The `header-actions` slot widget: reads the origin of the latest live frame from the feed store. Outside a
 * <SimulationProvider> (no store) or before the first frame it renders nothing instead of throwing.
 */
export default function HeaderSimulatedBadge() {
  const store = useContext(FeedStoreContext);
  return store ? <Connected store={store} /> : null;
}
