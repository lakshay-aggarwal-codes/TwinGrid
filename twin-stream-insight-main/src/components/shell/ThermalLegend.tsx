import {
  INLET_SCALE,
  OUTLET_SCALE,
  scaleSwatchAt,
  WAITING_COLOR,
  type ThermalScale,
} from "@/three/thermalMapping";
import { feedProvenance, noDataNotice, toReadout, type LiveFeed } from "@/three/visualizationModes";
import { FreshnessChip, ProvenanceBadge, formatAge } from "@/provenance";
import { StatusMessage } from "./StatusMessage";

interface ThermalLegendProps {
  /** FE-06: the stamped feed. Numbers are current, "last known" with their age, or absent -- never silently stale. */
  feed: LiveFeed;
}

function ScaleBar({ label, scale, currentC, lastKnown = false }: { label: string; scale: ThermalScale; currentC?: number; lastKnown?: boolean }) {
  const stops = [0, 0.25, 0.5, 0.75, 1];
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
        <span>{label}</span>
        {currentC !== undefined && (
          <span className={lastKnown ? "font-mono text-muted-foreground" : "font-mono text-foreground"} data-thermal-value={lastKnown ? "last-known" : "current"}>
            {currentC.toFixed(1)}°C
          </span>
        )}
      </div>
      <div className="h-2 w-full rounded-full overflow-hidden flex">
        {stops.slice(0, -1).map((t, i) => (
          <div
            key={t}
            className="flex-1 h-full"
            style={{
              background: `linear-gradient(to right, ${scaleSwatchAt(scale, t)}, ${scaleSwatchAt(scale, stops[i + 1])})`,
            }}
          />
        ))}
      </div>
      <div className="flex items-center justify-between text-[10px] text-muted-foreground font-mono">
        <span>{scale.min}°C</span>
        <span>{scale.max}°C</span>
      </div>
    </div>
  );
}

/**
 * Legend for Thermal view mode -- exists so a facility-wide-only value
 * never gets misread as spatial/per-rack data (non-negotiable #5). Shown
 * only while viewMode === "thermal"; see LiveTwin.tsx.
 */
export function ThermalLegend({ feed }: ThermalLegendProps) {
  const readout = toReadout(feed);
  const view = feedProvenance(feed);
  const lastKnown = readout.mode === "last-known";
  const reading =
    readout.mode === "none" ? null : { inletTempC: readout.state.server_inlet_temp_C, outletTempC: readout.state.server_outlet_temp_C };
  const notice = readout.mode === "none" ? noDataNotice(readout.freshness) : null;

  return (
    <div
      data-testid="thermal-legend"
      data-readout={readout.mode}
      className={`absolute bottom-4 left-4 w-64 rounded-lg border bg-card/90 backdrop-blur-sm p-3 space-y-3 ${
        lastKnown ? "border-dashed border-muted-foreground/60" : "border-border"
      }`}
    >
      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Thermal (facility-wide)</p>

      {feed.frame ? <ProvenanceBadge view={view} /> : <FreshnessChip view={view} />}

      {reading ? (
        <>
          {readout.mode === "last-known" && (
            <p data-testid="last-known" className="text-[11px] text-muted-foreground">
              Last known · {formatAge(readout.ageMs)}. Scene colours are neutral until the feed is live.
            </p>
          )}
          <ScaleBar label="Inlet (cold aisle)" scale={INLET_SCALE} currentC={reading.inletTempC} lastKnown={lastKnown} />
          <ScaleBar label="Outlet (hot aisle)" scale={OUTLET_SCALE} currentC={reading.outletTempC} lastKnown={lastKnown} />
        </>
      ) : (
        <div className="space-y-1.5">
          <span className="block h-2 w-2 rounded-full" style={{ backgroundColor: WAITING_COLOR }} aria-hidden="true" />
          {notice && <StatusMessage kind={notice.kind}>{notice.text}</StatusMessage>}
        </div>
      )}

      <p className="text-[10px] text-muted-foreground leading-snug">
        One reading for the whole facility, applied to every rack identically -- there is no
        per-rack sensor data.
      </p>
    </div>
  );
}
