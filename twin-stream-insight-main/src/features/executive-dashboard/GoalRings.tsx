import { useId, useState } from "react";
import { AlertTriangle, CheckCircle2, CircleDashed, Pencil } from "lucide-react";
import type { SlotWidgetProps } from "../types";
import { fmtNumber } from "./format";
import { GOAL_DEFS, goalView, parseTargetInput, type GoalDef, type GoalId, type GoalStatus } from "./goals";
import { setGoal, useGoals } from "./goalsStore";
import { useLiveSeries } from "./liveStore";
import { useModelRun } from "./useExecData";

const R = 30;
const C = 2 * Math.PI * R;

const STATUS_TEXT: Record<GoalStatus, string> = {
  within: "Within target",
  over: "Over target",
  "no-target": "No target set",
  "no-data": "No data yet",
};

function StatusIcon({ status }: { status: GoalStatus }) {
  if (status === "within") return <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5" />;
  if (status === "over") return <AlertTriangle aria-hidden="true" className="h-3.5 w-3.5" />;
  return <CircleDashed aria-hidden="true" className="h-3.5 w-3.5" />;
}

function Ring({ fill, status }: { fill: number; status: GoalStatus }) {
  return (
    <svg viewBox="0 0 80 80" className="h-20 w-20 -rotate-90" aria-hidden="true" focusable="false">
      <circle cx="40" cy="40" r={R} fill="none" stroke="currentColor" strokeOpacity="0.15" strokeWidth="7" />
      {status !== "no-data" && status !== "no-target" && (
        <circle
          cx="40"
          cy="40"
          r={R}
          fill="none"
          stroke="currentColor"
          strokeWidth="7"
          strokeLinecap="butt"
          /* Over target: a dashed ring, so the state is a shape and not only a colour. */
          strokeDasharray={status === "over" ? `${C * 0.06} ${C * 0.03}` : `${C * fill} ${C}`}
          strokeDashoffset={0}
          className={status === "over" ? "text-warning" : "text-primary"}
        />
      )}
    </svg>
  );
}

function Editor({ def, current, onDone }: { def: GoalDef; current: number | null; onDone: () => void }) {
  const inputId = useId();
  const [text, setText] = useState(current === null ? "" : String(current));
  const [error, setError] = useState<string | null>(null);
  const save = () => {
    const parsed = parseTargetInput(def.id, text);
    if ("reason" in parsed) {
      setError(parsed.reason);
      return;
    }
    setGoal(def.id, parsed.value);
    onDone();
  };
  return (
    <div
      className="space-y-1"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onDone();
        }
      }}
    >
      <label htmlFor={inputId} className="text-[11px] text-muted-foreground">
        {def.label} target{def.unit ? ` (${def.unit})` : ""}, at or below
      </label>
      <div className="flex gap-1">
        <input
          id={inputId}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          value={text}
          autoFocus
          aria-invalid={error !== null}
          aria-describedby={error ? `${inputId}-err` : undefined}
          onChange={(e) => {
            setText(e.target.value);
            setError(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              save();
            }
          }}
          className="w-full min-w-0 rounded border border-input bg-background px-1.5 py-1 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <button type="button" onClick={save} className="rounded border border-border px-2 text-xs hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          Save
        </button>
        <button type="button" onClick={onDone} className="rounded px-2 text-xs text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          Cancel
        </button>
      </div>
      <p className="text-[10px] text-muted-foreground">Leave empty to clear the target.</p>
      {error && (
        <p id={`${inputId}-err`} role="alert" className="text-[11px] text-destructive-text">
          {error}
        </p>
      )}
    </div>
  );
}

function GoalCard({ def, value, current, note }: { def: GoalDef; value: number | null; current: number | null; note: string }) {
  const [editing, setEditing] = useState(false);
  const view = goalView(def.id, value, current);
  const shown = value === null ? null : fmtNumber(value, def.decimals);
  return (
    <li className="card-grid-glow flex gap-3 rounded-lg p-3 list-none" data-goal={def.id} data-status={view.status}>
      <div className="relative shrink-0 text-foreground">
        <Ring fill={view.fill} status={view.status} />
        <span className="absolute inset-0 flex items-center justify-center font-mono text-[11px]" aria-hidden="true">
          {view.status === "no-data" || view.status === "no-target" ? "\u2014" : `${Math.round(view.fill * 100)}%`}
        </span>
      </div>
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-xs font-medium text-foreground">{def.label}</p>
        <p className="font-mono text-sm text-foreground">
          {shown ?? "NOT MEASURED"}
          {shown !== null && def.unit ? <span className="ml-1 text-xs text-muted-foreground">{def.unit}</span> : null}
        </p>
        <p className="inline-flex items-center gap-1 text-[11px] text-foreground" data-testid={`goal-${def.id}-status`}>
          <StatusIcon status={view.status} /> {STATUS_TEXT[view.status]}
          {view.target !== null ? ` (target \u2264 ${fmtNumber(view.target, def.decimals)}${def.unit ? ` ${def.unit}` : ""})` : ""}
        </p>
        <p className="text-[10px] text-muted-foreground">{note}</p>
        {editing ? (
          <Editor def={def} current={current} onDone={() => setEditing(false)} />
        ) : (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="inline-flex items-center gap-1 rounded px-1 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={`Edit the ${def.label} target`}
          >
            <Pencil aria-hidden="true" className="h-3 w-3" /> {current === null ? "Set target" : "Edit target"}
          </button>
        )}
      </div>
    </li>
  );
}

export default function GoalRings(_props: SlotWidgetProps) {
  const { goals, storageOk } = useGoals();
  const samples = useLiveSeries();
  const run = useModelRun();
  const latest = samples[samples.length - 1] ?? null;
  const model = run.status === "ready" ? run.data : null;

  const values: Record<GoalId, { value: number | null; note: string }> = {
    pue: { value: latest ? latest.pue : null, note: "Latest live tick (simulated)." },
    outlet: { value: latest ? latest.outletC : null, note: "Latest live tick (simulated)." },
    energy: { value: model ? model.total_energy_kwh : null, note: "24 h model estimate on simulated data." },
    carbon: { value: model ? model.total_co2_kg : null, note: model && !model.carbon_data_is_real ? "24 h model estimate, fallback carbon intensity." : "24 h model estimate on simulated data." },
  };

  return (
    <section aria-labelledby="exec-goals-heading" className="col-span-full space-y-2" data-testid="exec-goals">
      <h2 id="exec-goals-heading" className="text-sm font-semibold text-foreground">Goals</h2>
      <p className="text-[11px] text-muted-foreground">
        Targets are yours: kept in this browser only{storageOk ? "" : " (this browser refused to store them, so they last until you reload)"}. Each ring shows the value as a share of its target.
      </p>
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 p-0 m-0">
        {GOAL_DEFS.map((def) => (
          <GoalCard key={def.id} def={def} value={values[def.id].value} current={goals[def.id]} note={`${values[def.id].note}${goals[def.id] !== null && goals[def.id] === def.defaultTarget && def.defaultNote ? ` Target: ${def.defaultNote}.` : ""}`} />
        ))}
      </ul>
    </section>
  );
}
