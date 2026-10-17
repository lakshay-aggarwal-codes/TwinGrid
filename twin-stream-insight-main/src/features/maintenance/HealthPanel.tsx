import { StateBoundary } from "@/state/StateBoundary";
import { HEALTH_CUE, HEALTH_LABEL, latestText, needsAttention, trendText } from "./model";
import type { HealthAsset } from "./schema";
import { Sparkline } from "./Sparkline";
import { useHealth } from "./useMaintenance";

const BTN =
  "rounded-md border border-border bg-background px-2 py-1 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function StatusCue({ status }: { status: keyof typeof HEALTH_CUE }) {
  const cue = HEALTH_CUE[status];
  return (
    <span className="inline-flex items-center gap-1" data-status={status}>
      <span aria-hidden="true" className="font-mono">{cue.glyph}</span>
      {cue.word}
    </span>
  );
}

interface Props {
  canCreate: boolean;
  onCreate: (asset: HealthAsset) => void;
}

/** Per-asset health from stored telemetry, with each sensor's trend. No remaining life is shown as a number: there is none. */
export function HealthPanel({ canCreate, onCreate }: Props) {
  const { state, refetch } = useHealth();
  return (
    <section aria-labelledby="mx-health" className="card-grid-glow space-y-3 rounded-lg p-4" data-testid="health-panel">
      <div className="space-y-1">
        <h2 id="mx-health" className="text-sm font-semibold text-foreground">Asset health</h2>
        <p className="text-[11px] text-muted-foreground" data-testid="health-label">{HEALTH_LABEL}</p>
      </div>
      <StateBoundary state={state} onRetry={refetch} messages={{ loading: "Reading stored telemetry…", empty: "No assets are registered yet." }}>
        {(h) => {
          const measured = h.assets.filter((a) => a.sensor_count > 0);
          const bare = h.assets.filter((a) => a.sensor_count === 0);
          return (
            <div className="space-y-3">
              <p className="text-xs text-foreground" data-testid="health-counts">
                Last {h.window_hours} h: {h.counts.warning} warning, {h.counts.watch} watch, {h.counts.ok} ok, {h.counts.no_data} not measured.
              </p>
              <p className="rounded border border-dashed border-border px-2 py-1 text-[11px] text-foreground" data-testid="remaining-life">
                <strong>Remaining life: not available.</strong> {h.remaining_life.reason}
              </p>
              {measured.length === 0 && <p className="text-xs text-muted-foreground">No asset has a sensor with stored telemetry, so no health can be shown.</p>}
              {measured.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[40rem] text-left text-xs" data-testid="health-table">
                    <caption className="sr-only">Health and trend per sensor</caption>
                    <thead>
                      <tr className="border-b border-border text-muted-foreground">
                        <th scope="col" className="py-1 pr-3">Asset</th>
                        <th scope="col" className="py-1 pr-3">Health</th>
                        <th scope="col" className="py-1 pr-3">Sensors and trend</th>
                        <th scope="col" className="py-1" />
                      </tr>
                    </thead>
                    <tbody>
                      {measured.map((a) => (
                        <tr key={a.external_id} className="border-b border-border/60 align-top" data-testid={`health-row-${a.external_id}`}>
                          <th scope="row" className="py-2 pr-3 font-medium text-foreground">
                            {a.name}
                            <span className="block font-normal text-muted-foreground">{a.asset_type}</span>
                          </th>
                          <td className="py-2 pr-3"><StatusCue status={a.status} /></td>
                          <td className="space-y-2 py-2 pr-3">
                            {a.sensors.map((s) => (
                              <div key={s.external_id} className="space-y-0.5">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className="font-mono text-foreground">{s.measurand}</span>
                                  <span>{latestText(s)}</span>
                                  <StatusCue status={s.status} />
                                  <Sparkline series={s.series} label={`${s.measurand} trend over the last ${h.window_hours} hours`} />
                                </div>
                                <p className="text-muted-foreground">{trendText(s)}</p>
                                {s.reasons.length > 0 && <p className="text-muted-foreground">Why: {s.reasons.join("; ")}.</p>}
                              </div>
                            ))}
                          </td>
                          <td className="py-2">
                            {needsAttention(a.status) && (
                              <button type="button" className={BTN} disabled={!canCreate} onClick={() => onCreate(a)} data-testid={`create-from-${a.external_id}`}>
                                Create work order
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {bare.length > 0 && (
                <details className="text-[11px] text-muted-foreground" data-testid="not-measured">
                  <summary className="cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    {bare.length} assets have no sensor: health NOT MEASURED
                  </summary>
                  <p className="mt-1">{bare.map((a) => a.name).join(", ")}</p>
                </details>
              )}
            </div>
          );
        }}
      </StateBoundary>
    </section>
  );
}
