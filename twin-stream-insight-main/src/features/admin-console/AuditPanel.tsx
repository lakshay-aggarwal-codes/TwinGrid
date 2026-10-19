import { useEffect, useId, useState, type ReactNode } from "react";
import { StateBoundary } from "@/state/StateBoundary";
import { downloadAudit } from "./api";
import { actionErrorText } from "./errors";
import { AUDIT_PAGE_SIZE, EMPTY_AUDIT_FORM, EXPORT_MAX_ROWS, OUTCOME_WORD, auditQuery, describeDetails, timeText, type AuditForm } from "./model";
import { BTN, FIELD, SECTION, TD, TH } from "./shared";
import { useAudit } from "./useAdmin";

function Field({ label, children }: { label: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-xs text-foreground">{label}</label>
      {children(id)}
    </div>
  );
}

/** Saves a Blob through a temporary link. Skipped (and reported) where the browser cannot. */
function saveBlob(blob: Blob, filename: string): boolean {
  if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") return false;
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL?.(href);
  return true;
}

export function AuditPanel() {
  const [form, setForm] = useState<AuditForm>(EMPTY_AUDIT_FORM);
  const [applied, setApplied] = useState<AuditForm>(EMPTY_AUDIT_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  // Paging: `cursor` is the before_id of the page on screen; `trail` holds the cursors of the newer pages.
  const [cursor, setCursor] = useState<number | null>(null);
  const [trail, setTrail] = useState<(number | null)[]>([]);
  const [exportMsg, setExportMsg] = useState<{ kind: "status" | "alert"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const built = auditQuery(applied, { limit: AUDIT_PAGE_SIZE, beforeId: cursor });
  const { state, refetch } = useAudit(built.ok ? built.value : "", built.ok);
  // Keep the action choices while the next page loads, so the picker does not blank out and show the wrong option.
  const [actions, setActions] = useState<string[]>([]);
  useEffect(() => {
    if (state.status === "ready") setActions(state.data.actions);
  }, [state]);

  const apply = () => {
    const check = auditQuery(form);
    if (!check.ok) {
      setFormError(check.error);
      return;
    }
    setFormError(null);
    setApplied(form);
    setCursor(null);
    setTrail([]);
    setExportMsg(null);
  };
  const reset = () => {
    setForm(EMPTY_AUDIT_FORM);
    setApplied(EMPTY_AUDIT_FORM);
    setFormError(null);
    setCursor(null);
    setTrail([]);
  };

  const doExport = async (format: "csv" | "json") => {
    const q = auditQuery(applied);
    if (!q.ok) return;
    setBusy(true);
    setExportMsg(null);
    try {
      const r = await downloadAudit(q.value, format);
      const saved = saveBlob(r.blob, r.filename);
      const more = r.truncated ? ` Only the newest ${EXPORT_MAX_ROWS.toLocaleString("en")} matching rows are included.` : "";
      setExportMsg({ kind: "status", text: saved ? `Exported ${r.rows} rows as ${r.filename}.${more}` : `The export was ready (${r.rows} rows) but this browser could not save it.${more}` });
    } catch (e) {
      setExportMsg({ kind: "alert", text: actionErrorText(e, "export the audit log") });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="ad-audit" className={SECTION} data-testid="audit-panel">
      <h2 id="ad-audit" className="text-sm font-semibold text-foreground">Audit log</h2>
      <p className="text-xs text-muted-foreground">
        Append-only record of privileged actions. Filters apply to the list and to the export. An export is limited to the newest {EXPORT_MAX_ROWS.toLocaleString("en")} matching rows and is itself recorded here.
      </p>

      <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); apply(); }} data-testid="audit-filters">
        <Field label="Action">
          {(id) => (
            <select id={id} className={FIELD} value={form.action} onChange={(e) => setForm({ ...form, action: e.target.value })}>
              <option value="">Any</option>
              {actions.map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Outcome">
          {(id) => (
            <select id={id} className={FIELD} value={form.outcome} onChange={(e) => setForm({ ...form, outcome: e.target.value })}>
              <option value="">Any</option>
              {Object.entries(OUTCOME_WORD).map(([v, w]) => (
                <option key={v} value={v}>{w}</option>
              ))}
            </select>
          )}
        </Field>
        <Field label="User">{(id) => <input id={id} className={`${FIELD} w-32`} value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />}</Field>
        <Field label="Resource type">{(id) => <input id={id} className={`${FIELD} w-32`} value={form.resourceType} onChange={(e) => setForm({ ...form, resourceType: e.target.value })} />}</Field>
        <Field label="From">{(id) => <input id={id} type="datetime-local" className={FIELD} value={form.since} onChange={(e) => setForm({ ...form, since: e.target.value })} />}</Field>
        <Field label="To">{(id) => <input id={id} type="datetime-local" className={FIELD} value={form.until} onChange={(e) => setForm({ ...form, until: e.target.value })} />}</Field>
        <div className="flex gap-2">
          <button type="submit" className={BTN}>Apply filters</button>
          <button type="button" className={BTN} onClick={reset}>Clear</button>
        </div>
      </form>
      {formError && <p role="alert" className="text-xs text-destructive-text" data-testid="audit-form-error">{formError}</p>}

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={BTN} disabled={busy} onClick={() => void doExport("csv")} data-testid="export-csv">Export CSV</button>
        <button type="button" className={BTN} disabled={busy} onClick={() => void doExport("json")} data-testid="export-json">Export JSON</button>
        {exportMsg && (
          <p role={exportMsg.kind} className={`text-xs ${exportMsg.kind === "alert" ? "text-destructive-text" : "text-muted-foreground"}`} data-testid="export-message">{exportMsg.text}</p>
        )}
      </div>

      <StateBoundary state={state} onRetry={refetch} messages={{ loading: "Loading the audit log…", empty: "No audit rows match these filters." }}>
        {(page) => (
          <>
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full min-w-[44rem] border-collapse text-sm" data-testid="audit-table">
                <caption className="sr-only">Audit log, newest first</caption>
                <thead className="border-b border-border bg-muted/40">
                  <tr>
                    <th scope="col" className={TH}>Time</th>
                    <th scope="col" className={TH}>User</th>
                    <th scope="col" className={TH}>Action</th>
                    <th scope="col" className={TH}>Outcome</th>
                    <th scope="col" className={TH}>Resource</th>
                    <th scope="col" className={TH}>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((r) => (
                    <tr key={r.id} className="border-b border-border/60 last:border-0" data-testid={`audit-${r.id}`}>
                      <td className={TD}>{timeText(r.created_at)}</td>
                      <td className={TD}>{r.username ?? "—"}</td>
                      <td className={`${TD} font-mono`}>{r.action}</td>
                      <td className={TD}>{OUTCOME_WORD[r.outcome] ?? r.outcome}</td>
                      <td className={TD}>{r.resource_type ? `${r.resource_type}${r.resource_id ? ` ${r.resource_id}` : ""}` : "—"}</td>
                      <td className={`${TD} break-words text-muted-foreground`}>{describeDetails(r.details) || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className={BTN}
                disabled={trail.length === 0}
                onClick={() => {
                  const back = trail[trail.length - 1];
                  setTrail(trail.slice(0, -1));
                  setCursor(back ?? null);
                }}
                data-testid="audit-newer"
              >
                Newer
              </button>
              <button
                type="button"
                className={BTN}
                disabled={!page.has_more || page.next_before_id === null}
                onClick={() => {
                  setTrail([...trail, cursor]);
                  setCursor(page.next_before_id);
                }}
                data-testid="audit-older"
              >
                Older
              </button>
              <span className="text-xs text-muted-foreground">{page.items.length} rows on this page</span>
            </div>
          </>
        )}
      </StateBoundary>
    </section>
  );
}
