import type { RackViewEnvelope } from "./schemas";
import { toPowerReadout, toReadout, type Readout } from "./model";

function ValueCell({ r }: { r: Readout }) {
  const muted = r.kind !== "value";
  const showUnit = (r.kind === "value" || r.kind === "invalid") && r.unit !== null && r.valueText !== "No value";
  return (
    <span className={muted ? "text-muted-foreground" : "font-mono text-foreground"} data-testid="readout-value" data-kind={r.kind}>
      {r.valueText}
      {showUnit ? ` ${r.unit}` : ""}
    </span>
  );
}

function Details({ r }: { r: Readout }) {
  return (
    <div className="space-y-0.5 text-[11px] text-muted-foreground">
      <p>
        {r.provenanceLabel}
        {r.quality ? ` · quality ${r.quality}` : ""}
      </p>
      {r.timeText && <p>{r.timeText}</p>}
      {r.note && <p>{r.note}</p>}
      {r.lineage && <p className="font-mono break-all">{r.lineage}</p>}
    </div>
  );
}

/** One rack's own readings. Every value comes from this rack's envelope; there is no facility or cross-rack fallback. */
export function RackReadout({ view }: { view: RackViewEnvelope }) {
  const power = toPowerReadout(view.power, view.source_rack_id);
  return (
    <section aria-labelledby="rack-readout-heading" className="space-y-4" data-testid="rack-readout" data-rack={view.source_rack_id}>
      <header className="space-y-1">
        <h2 id="rack-readout-heading" className="text-base font-semibold text-foreground">
          Source rack {view.source_rack_id}
        </h2>
        <p className="text-xs font-mono text-muted-foreground break-all">{view.asset_external_id}</p>
        <p className="text-xs text-muted-foreground" data-testid="mode-label">
          Recorded dataset (historical), not live · stream {view.stream_id}
        </p>
      </header>

      <table className="w-full text-left text-sm">
        <caption className="mb-1 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">Temperature probes</caption>
        <thead className="sr-only">
          <tr>
            <th scope="col">Probe</th>
            <th scope="col">Reading</th>
            <th scope="col">Details</th>
          </tr>
        </thead>
        <tbody>
          {view.temperature_sensors.map((s) => {
            const r = toReadout(s.record, s.record_absent_reason);
            return (
              <tr key={s.sensor_external_id} className="border-t border-border align-top" data-testid="probe-row">
                <th scope="row" className="py-2 pr-3 font-normal">
                  <span className="block text-foreground">{s.source_label ?? s.sensor_external_id}</span>
                  <span className="block text-[11px] font-mono text-muted-foreground break-all">{s.sensor_external_id}</span>
                  {s.source_position_word && <span className="block text-[11px] text-muted-foreground">Position word in source: {s.source_position_word}</span>}
                </th>
                <td className="py-2 pr-3">
                  <ValueCell r={r} />
                </td>
                <td className="py-2">
                  <Details r={r} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="space-y-1 border-t border-border pt-3" data-testid="power-readout" data-power-kind={power.kind}>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{power.title}</h3>
        {power.readout ? (
          <>
            <ValueCell r={power.readout} />
            <Details r={power.readout} />
          </>
        ) : (
          <p className="text-sm text-muted-foreground">{power.detail}</p>
        )}
        {power.readout && <p className="text-[11px] text-muted-foreground">{power.detail}</p>}
      </div>
    </section>
  );
}
