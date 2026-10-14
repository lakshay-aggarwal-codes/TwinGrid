import { useState } from "react";
import { DIRECTION_WORD, ESTIMATE_LABEL, METRICS, deltaOf, fixed, signed } from "./metrics";
import { describeInputs, type LabInputs } from "./model";
import { MAX_SAVED, MAX_NAME, defaultSaveName, type SavedScenario, type Snapshot } from "./saved";

interface Props {
  baseline: Snapshot | null;
  current: Snapshot | null;
  saved: readonly SavedScenario[];
  storageOk: boolean;
  onSave: (name: string) => void;
  onRemove: (id: string) => void;
  onLoad: (inputs: LabInputs) => void;
  onUseAsBaseline: (inputs: LabInputs) => void;
  onExport: () => void;
  onCopyLink: () => void;
  notice: string;
}

const btn = "rounded border border-border bg-background px-2 py-1 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function SavedPanel({ baseline, current, saved, storageOk, onSave, onRemove, onLoad, onUseAsBaseline, onExport, onCopyLink, notice }: Props) {
  const [name, setName] = useState("");
  const full = saved.length >= MAX_SAVED;
  const columns: { key: string; title: string; snap: Snapshot | null; saved?: SavedScenario }[] = [
    { key: "baseline", title: "Baseline", snap: baseline },
    { key: "current", title: "Current", snap: current },
    ...saved.map((s) => ({ key: s.id, title: s.name, snap: s as Snapshot, saved: s })),
  ];

  return (
    <section aria-label="Saved scenarios" className="space-y-3 rounded-md border border-border bg-card p-3" data-testid="lab-saved">
      <h2 className="text-sm font-semibold text-foreground">Save, compare and share</h2>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Name
          <input value={name} maxLength={MAX_NAME} placeholder={current ? defaultSaveName(current.inputs) : "Scenario name"} onChange={(e) => setName(e.target.value)} className="w-56 rounded border border-border bg-background px-2 py-1 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        </label>
        <button type="button" className={btn} disabled={!current || full} onClick={() => { onSave(name.trim() === "" && current ? defaultSaveName(current.inputs) : name); setName(""); }}>
          Save current scenario
        </button>
        <button type="button" className={btn} onClick={onExport} disabled={!baseline && !current && saved.length === 0}>Export CSV</button>
        <button type="button" className={btn} onClick={onCopyLink}>Copy link</button>
        <span role="status" className="text-xs text-muted-foreground" data-testid="lab-notice">{notice}</span>
      </div>
      <p className="text-[11px] text-muted-foreground">
        {saved.length} of {MAX_SAVED} saved. Saved numbers are snapshots of the backend result at the time you saved them. {storageOk ? "Kept in this browser only." : "This browser could not store them: they will be lost on reload."} {ESTIMATE_LABEL}.
      </p>

      {saved.length > 0 && (
        <ul className="space-y-1" data-testid="lab-saved-list">
          {saved.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 rounded border border-border px-2 py-1 text-xs">
              <span className="min-w-0 truncate"><strong>{s.name}</strong> — {describeInputs(s.inputs)}</span>
              <span className="flex gap-1">
                <button type="button" className={btn} onClick={() => onLoad(s.inputs)} aria-label={`Load ${s.name} into the controls`}>Load</button>
                <button type="button" className={btn} onClick={() => onUseAsBaseline(s.inputs)} aria-label={`Use ${s.name} as the baseline`}>Use as baseline</button>
                <button type="button" className={btn} onClick={() => onRemove(s.id)} aria-label={`Delete ${s.name}`}>Delete</button>
              </span>
            </li>
          ))}
        </ul>
      )}

      {baseline && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-left text-xs" data-testid="lab-compare-table">
            <caption className="sr-only">Baseline, current and saved scenarios, with the difference from the baseline</caption>
            <thead className="text-muted-foreground">
              <tr>
                <th scope="col" className="py-1 pr-2 font-medium">Metric</th>
                {columns.map((c) => <th key={c.key} scope="col" className="py-1 pr-2 font-medium">{c.title}</th>)}
              </tr>
            </thead>
            <tbody>
              {METRICS.map((m) => (
                <tr key={m.id} className="border-t border-border">
                  <th scope="row" className="py-1 pr-2 font-normal text-foreground">{m.label}{m.unit ? ` (${m.unit})` : ""}</th>
                  {columns.map((c) => {
                    if (!c.snap) return <td key={c.key} className="py-1 pr-2 text-muted-foreground">—</td>;
                    const v = c.snap.metrics[m.id];
                    if (c.key === "baseline") return <td key={c.key} className="py-1 pr-2 tabular-nums">{fixed(v, m.precision)}</td>;
                    const d = deltaOf(baseline.metrics[m.id], v);
                    return (
                      <td key={c.key} className="py-1 pr-2 tabular-nums" data-testid={`lab-compare-${c.key}-${m.id}`}>
                        {fixed(v, m.precision)} <span className="text-muted-foreground"><span aria-hidden="true">{DIRECTION_WORD[d.direction].glyph}</span> {signed(d.delta, m.precision)}<span className="sr-only"> ({DIRECTION_WORD[d.direction].word})</span></span>
                        {m.id === "carbon" && !c.snap.carbonIsReal ? <span className="ml-1 text-[10px] text-muted-foreground">(fallback intensity)</span> : null}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
