import { useMemo } from "react";
import { Activity, Boxes } from "lucide-react";
import { RotateLink } from "@/components/transition/RotateLink";
import { FreshnessChip, ProvenanceStrip } from "@/provenance";
import { feedProvenance, type LiveFeed } from "@/three/visualizationModes";

interface Props {
  /** FE-08: the stamped live feed (frame + CURRENT freshness) from the feed store. */
  feed: LiveFeed;
}

/**
 * FE-08: the header states what the page is connected to, from the feed itself. It no longer claims "Systems Online"
 * (nothing here measures that), shows no browser clock (browser time is not data time), and the static SIMULATED
 * banner is replaced by the provenance strip, which says what the backend said about the origin -- or "Unverified source".
 */
export function DashboardHeader({ feed }: Props) {
  const view = useMemo(() => feedProvenance(feed), [feed]);

  return (
    <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-6 py-3 border-b border-border bg-card/80 backdrop-blur-sm">
      <div className="flex items-center gap-3">
        <div className="h-8 w-8 rounded-md bg-primary/20 flex items-center justify-center">
          <Activity className="h-5 w-5 text-primary" />
        </div>
        <h1 className="text-lg font-semibold tracking-tight text-foreground">
          TwinGrid —{" "}
          <span className="text-primary glow-text">Analytics</span>{" "}
        </h1>
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <RotateLink
          to="/"
          direction={-1}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-border text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <Boxes className="h-3.5 w-3.5" />
          Live Twin
        </RotateLink>
        {/* Mounted once on this page, so this is the one place freshness transitions are announced. */}
        <div data-testid="liveness" data-liveness={feed.freshness.state}>
          {feed.frame ? (
            <div data-testid="origin-banner" data-origin-tone={view.origin.state}>
              <ProvenanceStrip view={view} announce />
            </div>
          ) : (
            <FreshnessChip view={view} announce />
          )}
        </div>
      </div>
    </header>
  );
}
