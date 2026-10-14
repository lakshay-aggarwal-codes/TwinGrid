import { MEASURANDS } from "@/telemetry/history/model";
import { useFeed } from "@/telemetry/useFeed";
import { formatAge } from "@/provenance";
import { toReadout, type LiveFeed } from "@/three/visualizationModes";
import type { ReadAt } from "./dataset";
import { clockUtc, formatReading, formatSpan } from "./format";
import { isReplaying } from "./model";
import { useReplay } from "./ReplayContext";

function ReplayCell({ label, unit, read, measurand }: { label: string; unit: string | null; read: ReadAt | undefined; measurand: string }) {
  let value = "—";
  let note = "No stored data for this measurand.";
  let tone = "text-muted-foreground";
  if (read?.kind === "value") {
    value = formatReading(measurand, read.value);
    note = read.ageMs === 0 ? `Sample at ${clockUtc(read.atMs)}` : `Held from the sample at ${clockUtc(read.atMs)} (${formatSpan(read.ageMs)} earlier)`;
    if (read.stale) note += " — older than the sampling interval allows";
    tone = "text-foreground";
  } else if (read?.kind === "gap") {
    note = `No data: stored gap ${clockUtc(read.fromMs)} to ${clockUtc(read.toMs)} (${formatSpan(read.durationS * 1000)})`;
  } else if (read?.kind === "before-start") {
    note = `No data yet: first stored sample is at ${clockUtc(read.firstMs)}`;
  }
  return (
    <div className="rounded-md border border-border bg-card p-3" data-testid={`replay-kpi-${measurand}`} data-kind={read?.kind ?? "none"}>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`text-xl font-semibold tabular-nums ${tone}`}>
        {value}
        {read?.kind === "value" && unit ? <span className="ml-1 text-xs font-normal text-muted-foreground">{unit}</span> : null}
        {read?.kind === "value" && !unit ? <span className="ml-1 text-xs font-normal text-muted-foreground">(unit not reported)</span> : null}
      </p>
      <p className="text-[11px] text-muted-foreground">{note}</p>
    </div>
  );
}

/** The five stored measurands at the cursor (replay), or the live feed's own readings (live). Never mixed in one view. */
export function ReplayKpis() {
  const { state, snapshot, load } = useReplay();
  const frame = useFeed((v) => v.frame);
  const freshness = useFeed((v) => v.freshness);
  const replaying = isReplaying(state);
  const units = new Map(load.state.status === "ready" ? load.state.data.dataset.series.map((s) => [s.measurand, s.unit] as const) : []);

  if (replaying) {
    return (
      <section aria-label="Stored values at the replay time" className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5" data-testid="replay-kpis" data-source="replay">
        {MEASURANDS.map((m) => (
          <ReplayCell key={m.id} label={m.label} unit={units.get(m.id) ?? null} read={snapshot?.[m.id]} measurand={m.id} />
        ))}
      </section>
    );
  }

  const feed: LiveFeed = { frame, freshness };
  const readout = toReadout(feed);
  const live = readout.mode === "current" ? readout.state : readout.mode === "last-known" ? readout.state : null;
  return (
    <section aria-label="Live feed readings" className="space-y-2" data-testid="replay-kpis" data-source="live">
      <p className="text-xs text-muted-foreground">
        {readout.mode === "current" && "Live feed (simulated twin)."}
        {readout.mode === "last-known" && `Last known values, ${formatAge(readout.ageMs)} — the feed is ${readout.freshness}.`}
        {readout.mode === "none" && `No live values: the feed is ${readout.freshness}.`}
      </p>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5">
        {MEASURANDS.map((m) => {
          const raw = live ? (live as unknown as Record<string, unknown>)[m.id] : undefined;
          return (
            <div key={m.id} className="rounded-md border border-border bg-card p-3" data-testid={`replay-kpi-${m.id}`}>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{m.label}</p>
              <p className="text-xl font-semibold tabular-nums text-foreground">{typeof raw === "number" ? formatReading(m.id, raw) : "—"}</p>
            </div>
          );
        })}
      </div>
    </section>
  );
}
