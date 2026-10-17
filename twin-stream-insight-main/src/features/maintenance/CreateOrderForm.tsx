import { useId, useState, type ReactNode } from "react";
import { useInbox } from "../alerts-centre/useInbox";
import { Input } from "@/components/ui/input";
import { writeErrorText } from "./errors";
import { EMPTY_FORM, MAX_ASSIGNEE, MAX_DESCRIPTION, MAX_TITLE, PRIORITY_LABEL, parseCreate, type CreateForm, type FormErrors, type SourceKind } from "./model";
import { PRIORITIES, type WorkOrder } from "./schema";
import { useHealth, useWorkOrderActions } from "./useMaintenance";

const BTN =
  "rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const SELECT =
  "w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const SOURCES: ReadonlyArray<{ kind: SourceKind; label: string }> = [
  { kind: "manual", label: "By hand" },
  { kind: "alert", label: "From an alert" },
  { kind: "health", label: "From a health warning" },
];

interface Props {
  form: CreateForm;
  onChange: (next: CreateForm) => void;
  canCreate: boolean;
  /** Called with the server's row after a successful create. */
  onCreated?: (o: WorkOrder) => void;
}

function Field({ id, label, error, children }: { id: string; label: string; error?: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-xs font-medium text-foreground">{label}</label>
      {children}
      {error && (
        <p id={`${id}-err`} role="alert" className="text-[11px] text-destructive">{error}</p>
      )}
    </div>
  );
}

/** Creates a work order by hand, from an alert in the inbox, or from a health row. The server checks the alert and asset exist. */
export function CreateOrderForm({ form, onChange, canCreate, onCreated }: Props) {
  const uid = useId();
  const id = (n: string) => `${uid}-${n}`;
  const { create } = useWorkOrderActions();
  const inbox = useInbox();
  const health = useHealth();
  const [errors, setErrors] = useState<FormErrors>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [done, setDone] = useState<WorkOrder | null>(null);
  const [busy, setBusy] = useState(false);

  const set = <K extends keyof CreateForm>(k: K, v: CreateForm[K]) => onChange({ ...form, [k]: v });
  const alerts = inbox.state.status === "ready" ? inbox.state.data.slice(0, 50) : [];
  const assets = health.state.status === "ready" ? health.state.data.assets.filter((a) => a.sensor_count > 0) : [];
  const sensors = assets.find((a) => a.external_id === form.assetExternalId)?.sensors ?? [];

  const submit = async (e: { preventDefault: () => void }) => {
    e.preventDefault();
    setDone(null);
    setFailure(null);
    const parsed = parseCreate(form);
    if (!parsed.ok) {
      setErrors(parsed.errors);
      return;
    }
    setErrors({});
    setBusy(true);
    try {
      const row = await create(parsed.body);
      setDone(row);
      onChange(EMPTY_FORM);
      onCreated?.(row);
    } catch (err) {
      setFailure(writeErrorText(err));
    } finally {
      setBusy(false);
    }
  };

  if (!canCreate) {
    return (
      <section aria-labelledby="mx-new" className="card-grid-glow rounded-lg p-4" data-testid="create-form-denied">
        <h2 id="mx-new" className="text-sm font-semibold text-foreground">New work order</h2>
        <p className="mt-1 text-xs text-muted-foreground">Only operators can create work orders. You can read and follow them here.</p>
      </section>
    );
  }

  return (
    <section aria-labelledby="mx-new" className="card-grid-glow space-y-3 rounded-lg p-4" data-testid="create-form">
      <h2 id="mx-new" className="text-sm font-semibold text-foreground">New work order</h2>
      <form onSubmit={submit} noValidate className="space-y-3">
        <fieldset className="space-y-1">
          <legend className="text-xs font-medium text-foreground">Raised</legend>
          <div className="flex flex-wrap gap-3 text-xs">
            {SOURCES.map((s) => (
              <label key={s.kind} className="inline-flex items-center gap-1.5">
                <input type="radio" name={id("source")} checked={form.sourceKind === s.kind} onChange={() => set("sourceKind", s.kind)} />
                {s.label}
              </label>
            ))}
          </div>
        </fieldset>

        {form.sourceKind === "alert" && (
          <Field id={id("alert")} label="Alert" error={errors.alertId}>
            <select id={id("alert")} className={SELECT} value={form.alertId} onChange={(e) => set("alertId", e.target.value)} aria-invalid={errors.alertId ? true : undefined}>
              <option value="">{inbox.state.status === "ready" ? "Choose an alert" : "Loading alerts…"}</option>
              {alerts.map((a) => (
                <option key={a.id} value={String(a.id)}>
                  #{a.id} · {a.severity} · {a.message.slice(0, 70)}
                </option>
              ))}
            </select>
          </Field>
        )}

        {form.sourceKind === "health" && (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id={id("asset")} label="Asset" error={errors.assetExternalId}>
              <select id={id("asset")} className={SELECT} value={form.assetExternalId} onChange={(e) => onChange({ ...form, assetExternalId: e.target.value, measurand: "" })} aria-invalid={errors.assetExternalId ? true : undefined}>
                <option value="">{health.state.status === "ready" ? "Choose an asset" : "Loading assets…"}</option>
                {assets.map((a) => (
                  <option key={a.external_id} value={a.external_id}>{a.name}</option>
                ))}
              </select>
            </Field>
            <Field id={id("sensor")} label="Sensor (optional)">
              <select id={id("sensor")} className={SELECT} value={form.measurand} onChange={(e) => set("measurand", e.target.value)} disabled={sensors.length === 0}>
                <option value="">Whole asset</option>
                {sensors.map((s) => (
                  <option key={s.external_id} value={s.measurand}>{s.measurand}</option>
                ))}
              </select>
            </Field>
          </div>
        )}

        <Field id={id("title")} label={form.sourceKind === "manual" ? "Title" : "Title (optional, a default is written)"} error={errors.title}>
          <Input id={id("title")} value={form.title} onChange={(e) => set("title", e.target.value)} aria-invalid={errors.title ? true : undefined} aria-describedby={errors.title ? `${id("title")}-err` : undefined} placeholder={`At most ${MAX_TITLE} characters`} />
        </Field>
        <Field id={id("desc")} label="Description (optional)" error={errors.description}>
          <textarea id={id("desc")} rows={2} value={form.description} onChange={(e) => set("description", e.target.value)} className={SELECT} placeholder={`At most ${MAX_DESCRIPTION} characters`} />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field id={id("prio")} label="Priority">
            <select id={id("prio")} className={SELECT} value={form.priority} onChange={(e) => set("priority", e.target.value as CreateForm["priority"])}>
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>{PRIORITY_LABEL[p]}</option>
              ))}
            </select>
          </Field>
          <Field id={id("who")} label="Assignee (optional)" error={errors.assignee}>
            <Input id={id("who")} value={form.assignee} onChange={(e) => set("assignee", e.target.value)} placeholder={`Username, at most ${MAX_ASSIGNEE} characters`} />
          </Field>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button type="submit" className={BTN} disabled={busy} data-testid="create-submit">
            {busy ? "Creating…" : "Create work order"}
          </button>
          {done && (
            <p role="status" className="text-xs text-foreground" data-testid="create-done">
              Work order #{done.id} created ({done.title}).
            </p>
          )}
          {failure && (
            <p role="alert" className="text-xs text-destructive" data-testid="create-failed">{failure}</p>
          )}
        </div>
      </form>
    </section>
  );
}
