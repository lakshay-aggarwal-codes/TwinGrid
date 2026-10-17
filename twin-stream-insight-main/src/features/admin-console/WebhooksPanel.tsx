import { useId, useState } from "react";
import { StateBoundary } from "@/state/StateBoundary";
import { actionErrorText } from "./errors";
import { KIND_WORD, deliveryText, parseWebhookUrl, timeText, webhookLabel } from "./model";
import { BTN, FIELD, SECTION, TD, TH } from "./shared";
import type { TestResult, Webhook } from "./schema";
import { useDeliveries, useWebhookActions, useWebhooks } from "./useAdmin";

function WebhookRow({ w }: { w: Webhook }) {
  const { replace, remove, test } = useWebhookActions();
  const editId = useId();
  const [editing, setEditing] = useState(false);
  const [url, setUrl] = useState("");
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TestResult | null>(null);
  const [saved, setSaved] = useState(false);

  const run = async (what: string, fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await fn();
    } catch (e) {
      setError(actionErrorText(e, what));
    } finally {
      setBusy(false);
    }
  };
  const save = () => {
    const parsed = parseWebhookUrl(url);
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    void run("change this webhook", async () => {
      await replace(w.id, parsed.value);
      setUrl("");
      setEditing(false);
      setSaved(true);
    });
  };

  return (
    <li className="space-y-1.5 border-b border-border/60 py-2 text-xs" data-testid={`webhook-${w.id}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-mono text-foreground" data-testid={`webhook-${w.id}-label`}>{webhookLabel(w)}</span>
        <span className="text-muted-foreground">path and query hidden · id {w.id}</span>
      </div>
      <p className="text-muted-foreground" data-testid={`webhook-${w.id}-last`}>
        {w.last_delivery ? `Last delivery (${KIND_WORD[w.last_delivery.kind]}, ${timeText(w.last_delivery.at)}): ${deliveryText(w.last_delivery)}` : "No delivery recorded yet."}
      </p>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={BTN} disabled={busy} onClick={() => void run("send a test event", async () => setResult(await test(w.id)))} data-testid={`webhook-${w.id}-test`}>
          Send test event
        </button>
        <button type="button" className={BTN} disabled={busy} onClick={() => { setEditing((v) => !v); setError(null); }} aria-expanded={editing} data-testid={`webhook-${w.id}-edit`}>
          {editing ? "Cancel edit" : "Change URL"}
        </button>
        {confirmRemove ? (
          <>
            <button type="button" className={BTN} disabled={busy} onClick={() => void run("remove this webhook", () => remove(w.id))} data-testid={`webhook-${w.id}-confirm`}>
              Confirm remove
            </button>
            <button type="button" className={BTN} disabled={busy} onClick={() => setConfirmRemove(false)}>Keep</button>
          </>
        ) : (
          <button type="button" className={BTN} disabled={busy} onClick={() => setConfirmRemove(true)} data-testid={`webhook-${w.id}-remove`}>Remove</button>
        )}
      </div>
      {editing && (
        <div className="flex flex-wrap items-end gap-2">
          <div className="space-y-1">
            <label htmlFor={editId} className="block text-foreground">New URL (https, public)</label>
            <input id={editId} className={`${FIELD} w-72 max-w-full`} value={url} onChange={(e) => setUrl(e.target.value)} autoComplete="off" spellCheck={false} data-testid={`webhook-${w.id}-url`} />
          </div>
          <button type="button" className={BTN} disabled={busy} onClick={save} data-testid={`webhook-${w.id}-save`}>Save URL</button>
        </div>
      )}
      {result && (
        <p role="status" className="text-foreground" data-testid={`webhook-${w.id}-result`}>
          Test event: {deliveryText(result)}.
        </p>
      )}
      {saved && <p role="status" className="text-muted-foreground" data-testid={`webhook-${w.id}-saved`}>URL changed. It is not shown again.</p>}
      {error && <p role="alert" className="text-destructive" data-testid={`webhook-${w.id}-error`}>{error}</p>}
    </li>
  );
}

function AddWebhook() {
  const { create } = useWebhookActions();
  const id = useId();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [added, setAdded] = useState(false);
  const submit = async () => {
    const parsed = parseWebhookUrl(url);
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    setBusy(true);
    setError(null);
    setAdded(false);
    try {
      await create(parsed.value);
      setUrl("");
      setAdded(true);
    } catch (e) {
      setError(actionErrorText(e, "add this webhook"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); void submit(); }} data-testid="webhook-add">
      <div className="space-y-1">
        <label htmlFor={id} className="block text-xs text-foreground">Add a webhook URL (https, public)</label>
        <input id={id} className={`${FIELD} w-80 max-w-full`} value={url} onChange={(e) => setUrl(e.target.value)} autoComplete="off" spellCheck={false} data-testid="webhook-add-url" />
      </div>
      <button type="submit" className={BTN} disabled={busy} data-testid="webhook-add-submit">Add webhook</button>
      {added && <p role="status" className="text-xs text-muted-foreground" data-testid="webhook-added">Added. The URL is not shown again.</p>}
      {error && <p role="alert" className="w-full text-xs text-destructive" data-testid="webhook-add-error">{error}</p>}
    </form>
  );
}

function DeliveryLog({ hooks }: { hooks: Webhook[] }) {
  const [filter, setFilter] = useState("");
  const filterId = useId();
  const { state, refetch } = useDeliveries(filter || null);
  return (
    <div className="space-y-2" data-testid="delivery-log">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h3 className="text-xs font-semibold text-foreground">Delivery log</h3>
        <div className="flex items-end gap-2">
          <div className="space-y-1">
            <label htmlFor={filterId} className="block text-xs text-foreground">Webhook</label>
            <select id={filterId} className={FIELD} value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">All</option>
              {hooks.map((h) => (
                <option key={h.id} value={h.id}>{webhookLabel(h)}</option>
              ))}
            </select>
          </div>
          <button type="button" className={BTN} onClick={refetch}>Refresh</button>
        </div>
      </div>
      <StateBoundary state={state} onRetry={refetch} messages={{ loading: "Loading deliveries…", empty: "No deliveries recorded yet." }}>
        {(d) => (
          <>
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full min-w-[34rem] border-collapse text-sm">
                <caption className="sr-only">Recent webhook deliveries, newest first</caption>
                <thead className="border-b border-border bg-muted/40">
                  <tr>
                    <th scope="col" className={TH}>Time</th>
                    <th scope="col" className={TH}>Kind</th>
                    <th scope="col" className={TH}>Host</th>
                    <th scope="col" className={TH}>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {d.deliveries.map((r, i) => (
                    <tr key={`${r.at}-${r.webhook_id}-${i}`} className="border-b border-border/60 last:border-0" data-testid="delivery-row">
                      <td className={TD}>{timeText(r.at)}</td>
                      <td className={TD}>{KIND_WORD[r.kind]}</td>
                      <td className={`${TD} font-mono`}>{r.host}</td>
                      <td className={TD}>{deliveryText(r)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-[11px] text-muted-foreground">{d.note}</p>
          </>
        )}
      </StateBoundary>
    </div>
  );
}

export function WebhooksPanel() {
  const { state, refetch } = useWebhooks();
  return (
    <section aria-labelledby="ad-webhooks" className={SECTION} data-testid="webhooks-panel">
      <h2 id="ad-webhooks" className="text-sm font-semibold text-foreground">Webhooks</h2>
      <p className="text-xs text-muted-foreground">
        Subscribers receive alert events. A URL can carry a secret, so it is shown only as scheme, host and port, and is not shown again after you save it. Test events are labelled as tests.
      </p>
      <AddWebhook />
      <StateBoundary state={state} onRetry={refetch} messages={{ loading: "Loading webhooks…", empty: "No webhooks are registered." }}>
        {(data) => (
          <>
            <p className="text-xs text-foreground" data-testid="webhook-simulated-note">
              Alerts from simulated data {data.fires_for_simulated_alerts ? "do" : "do not"} fire webhooks on this server.{" "}
              {data.webhooks.length} of {data.max} subscribers in use.
            </p>
            <ul aria-label="Registered webhooks">
              {data.webhooks.map((w) => (
                <WebhookRow key={w.id} w={w} />
              ))}
            </ul>
            <DeliveryLog hooks={data.webhooks} />
          </>
        )}
      </StateBoundary>
    </section>
  );
}
