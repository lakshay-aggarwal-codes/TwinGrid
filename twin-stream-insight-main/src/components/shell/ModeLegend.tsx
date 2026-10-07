import {
  MODE_LABELS,
  feedProvenance,
  getModeReadings,
  isCarbonDataFallback,
  noDataNotice,
  toReadout,
  type LiveFeed,
  type VisualizationMode,
} from "@/three/visualizationModes";
import { ThermalLegend } from "./ThermalLegend";
import { FileText } from "lucide-react";
import { StatusMessage } from "./StatusMessage";
import { FreshnessChip, ProvenanceBadge, formatAge } from "@/provenance";
import { buildSustainabilityReport, type Report } from "@/reports/reports";

interface ModeLegendProps {
  mode: VisualizationMode;
  /** FE-06: the stamped feed (frame + current freshness). */
  feed: LiveFeed;
  /** Stage 13: hands a freshly built report to the page-level viewer. */
  onGenerateReport: (report: Report) => void;
}

/**
 * Physical mode has nothing to show -- no legend renders. Thermal (Stage 7)
 * gets its own dedicated legend (two real gradient scales, inlet/outlet)
 * since a flat key-value list can't represent that well. Energy/Cooling/
 * Sustainability (Stage 8) share this generic panel. Either way, this is
 * the ONLY place the underlying real numbers are surfaced -- the 3D racks
 * themselves only carry color, so without a legend a viewer would have no
 * way to know what a color actually means.
 *
 * FE-06: numbers are current only while the feed is live. Stale / disconnected / reconnecting show them as
 * "Last known" with their age in a muted, dashed style; connecting / unavailable show a state notice, never 0.
 */
export function ModeLegend({ mode, feed, onGenerateReport }: ModeLegendProps) {
  if (mode === "physical") return null;

  if (mode === "thermal") return <ThermalLegend feed={feed} />;

  const readout = toReadout(feed);
  const view = feedProvenance(feed);
  const readings = readout.mode === "none" ? [] : getModeReadings(mode, readout.state);
  const lastKnown = readout.mode === "last-known";
  const notice = readout.mode === "none" ? noDataNotice(readout.freshness) : null;

  return (
    <div
      data-testid="mode-legend"
      data-readout={readout.mode}
      className={`absolute bottom-4 left-4 rounded-md border bg-card/85 backdrop-blur-sm px-3.5 py-2.5 max-w-[260px] ${
        lastKnown ? "border-dashed border-muted-foreground/60" : "border-border"
      }`}
    >
      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
        {MODE_LABELS[mode]} — Facility-wide
      </p>
      <div className="mb-1.5">{feed.frame ? <ProvenanceBadge view={view} /> : <FreshnessChip view={view} />}</div>
      {notice ? (
        <StatusMessage kind={notice.kind}>{notice.text}</StatusMessage>
      ) : (
        <div className="space-y-0.5">
          {readout.mode === "last-known" && (
            <p data-testid="last-known" className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Last known · {formatAge(readout.ageMs)}
            </p>
          )}
          {readings.map((r) => (
            <div key={r.label} className="flex items-baseline justify-between gap-3 font-mono text-xs">
              <span className="text-muted-foreground">{r.label}</span>
              <span className={lastKnown ? "text-muted-foreground" : "text-foreground"} data-value={lastKnown ? "last-known" : "current"}>
                {r.value}
              </span>
            </div>
          ))}
        </div>
      )}
      <p className="text-[10px] text-muted-foreground mt-1.5 leading-snug">
        Every rack shares this same value — no per-rack data exists yet.
      </p>
      {mode === "sustainability" && readout.mode === "current" && (
        <button
          onClick={() => onGenerateReport(buildSustainabilityReport(readout.state))}
          className="mt-2 w-full flex items-center justify-center gap-1.5 rounded border border-border px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
        >
          <FileText className="h-3 w-3" /> Generate sustainability report
        </button>
      )}
      {readout.mode !== "none" && isCarbonDataFallback(readout.state) && (
        <p className="text-[10px] text-warning mt-1 leading-snug">
          Carbon intensity is a flat fallback figure, not live grid data.
        </p>
      )}
    </div>
  );
}

/**
 * Text overlay for the 3D view while the feed is not live: scene colours are neutral (see `currentState`), and this says
 * why. Renders nothing when the feed is live. The wording comes from the FE-05 freshness chip, so it carries the age
 * ("Stale · last update 42 s ago") and never reads as current. Not a live region: the header announces transitions.
 */
export function FeedOverlay({ feed }: { feed: LiveFeed }) {
  if (toReadout(feed).mode === "current") return null;
  const view = feedProvenance(feed);
  return (
    <div
      data-testid="feed-overlay"
      data-feed-state={feed.freshness.state}
      className="pointer-events-none absolute top-3 left-1/2 -translate-x-1/2 flex items-center gap-2 rounded-md border border-dashed border-muted-foreground/60 bg-card/90 px-3 py-1.5 text-xs text-foreground backdrop-blur-sm"
    >
      <FreshnessChip view={view} />
      <span className="text-muted-foreground">Scene colours are neutral until the feed is live.</span>
    </div>
  );
}
