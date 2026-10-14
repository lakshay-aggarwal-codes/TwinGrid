import { DIRECTION_TEXT, directionOf, formatDelta, formatReading, fullUtc } from "./format";
import { isReplaying } from "./model";
import { useReplay } from "./ReplayContext";

/** Time A (the cursor) against time B: B minus A per measurand. A side with no stored value is "unavailable", never filled in. */
export function CompareCard() {
  const { state, deltas } = useReplay();
  if (!state.compareOn) return null;
  const header = (
    <p className="text-xs text-muted-foreground">
      A = {state.cursorMs === null ? "—" : fullUtc(state.cursorMs)}. B = {state.compareBMs === null ? "not set" : fullUtc(state.compareBMs)}.
    </p>
  );
  if (!isReplaying(state) || state.compareBMs === null || deltas === null) {
    return (
      <section aria-label="Compare two times" className="space-y-1 rounded-md border border-border bg-card p-3" data-testid="replay-compare">
        {header}
        <p className="text-sm text-muted-foreground">{!isReplaying(state) ? "Move the time slider to choose time A." : "Choose time B: move the slider, then press “Set B to this time”."}</p>
      </section>
    );
  }
  return (
    <section aria-label="Compare two times" className="space-y-2 rounded-md border border-border bg-card p-3" data-testid="replay-compare">
      {header}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px] text-left text-xs">
          <caption className="sr-only">Stored values at time A and time B, and B minus A</caption>
          <thead className="text-muted-foreground">
            <tr>
              <th scope="col" className="py-1 pr-2 font-medium">Measurand</th>
              <th scope="col" className="py-1 pr-2 font-medium">A</th>
              <th scope="col" className="py-1 pr-2 font-medium">B</th>
              <th scope="col" className="py-1 pr-2 font-medium">B − A</th>
              <th scope="col" className="py-1 font-medium">Change</th>
            </tr>
          </thead>
          <tbody>
            {deltas.map((r) => {
              if (r.status === "unavailable") {
                const why = r.missing === "both" ? "A and B have no stored value" : r.missing === "a" ? "A has no stored value" : "B has no stored value";
                return (
                  <tr key={r.measurand} data-testid={`replay-delta-${r.measurand}`} data-status="unavailable" className="border-t border-border">
                    <th scope="row" className="py-1 pr-2 font-normal text-foreground">{r.label}</th>
                    <td colSpan={4} className="py-1 text-muted-foreground">Unavailable: {why} (gap, before the first sample, or no data).</td>
                  </tr>
                );
              }
              const dir = DIRECTION_TEXT[directionOf(r.delta)];
              const unit = r.unit ?? "";
              return (
                <tr key={r.measurand} data-testid={`replay-delta-${r.measurand}`} data-status="ok" className="border-t border-border">
                  <th scope="row" className="py-1 pr-2 font-normal text-foreground">{r.label}</th>
                  <td className="py-1 pr-2 tabular-nums">{formatReading(r.measurand, r.a)} {unit}{r.aStale ? " (held, old)" : ""}</td>
                  <td className="py-1 pr-2 tabular-nums">{formatReading(r.measurand, r.b)} {unit}{r.bStale ? " (held, old)" : ""}</td>
                  <td className="py-1 pr-2 tabular-nums">{formatDelta(r.measurand, r.delta)} {unit}</td>
                  <td className="py-1 tabular-nums">
                    <span aria-hidden="true">{dir.glyph} </span>
                    <span className="sr-only">{dir.word}, </span>
                    {r.pct === null ? "no percent (A is 0)" : `${r.pct > 0 ? "+" : r.pct < 0 ? "−" : ""}${Math.abs(r.pct).toFixed(1)}%`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
