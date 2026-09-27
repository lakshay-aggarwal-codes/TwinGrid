import {
  INLET_SCALE,
  OUTLET_SCALE,
  scaleSwatchAt,
  WAITING_COLOR,
  type ThermalReading,
  type ThermalScale,
} from "@/three/thermalMapping";

interface ThermalLegendProps {
  reading: ThermalReading | null;
}

function ScaleBar({ label, scale, currentC }: { label: string; scale: ThermalScale; currentC?: number }) {
  const stops = [0, 0.25, 0.5, 0.75, 1];
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
        <span>{label}</span>
        {currentC !== undefined && <span className="font-mono text-foreground">{currentC.toFixed(1)}°C</span>}
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
export function ThermalLegend({ reading }: ThermalLegendProps) {
  return (
    <div className="absolute bottom-4 left-4 w-64 rounded-lg border border-border bg-card/90 backdrop-blur-sm p-3 space-y-3">
      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Thermal (facility-wide)</p>

      {reading ? (
        <>
          <ScaleBar label="Inlet (cold aisle)" scale={INLET_SCALE} currentC={reading.inletTempC} />
          <ScaleBar label="Outlet (hot aisle)" scale={OUTLET_SCALE} currentC={reading.outletTempC} />
        </>
      ) : (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: WAITING_COLOR }} />
          Waiting for live data…
        </div>
      )}

      <p className="text-[10px] text-muted-foreground leading-snug">
        One reading for the whole facility, applied to every rack identically -- there is no
        per-rack sensor data.
      </p>
    </div>
  );
}
