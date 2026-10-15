import { useContext, useState, useSyncExternalStore } from "react";
import { AlertTriangle, HelpCircle } from "lucide-react";
import { FeedStoreContext } from "@/telemetry/useFeed";
import { StateBoundary } from "@/state/StateBoundary";
import { LiveWhy } from "./LiveWhy";
import { ModelPassportButton } from "./ModelPassportButton";
import { deviationSentence, featureLabel, scoreSentence, type Explanation } from "./model";
import { useAlertExplanation } from "./usePassport";

const noSubscribe = () => () => undefined;

/** The live frame's anomaly status, or null outside a feed provider or before the first frame. */
function useLiveStatus(): { explanation?: unknown; episode?: { alert_id?: number | null } | null } | null {
  const store = useContext(FeedStoreContext);
  return useSyncExternalStore(
    store ? store.subscribe : noSubscribe,
    () => (store ? ((store.getView().frame?.value.anomaly_status as never) ?? null) : null),
    () => null,
  );
}

function Bar({ position }: { position: number }) {
  const at = Math.max(0, Math.min(1, position)) * 100;
  return (
    <div aria-hidden="true" className="relative h-2 w-24 rounded bg-muted">
      <div className="absolute inset-y-0 w-0.5 bg-foreground" style={{ left: `${at}%` }} />
    </div>
  );
}

function Body({ data, alertId }: { data: Explanation; alertId: number }) {
  const live = useLiveStatus();
  const liveForThis = live?.episode?.alert_id === alertId ? live.explanation : undefined;
  return (
    <div className="space-y-3" data-testid="alert-explanation-body">
      {data.score_vs_threshold ? (
        <p className="text-xs" data-testid="explanation-score">
          {scoreSentence(data.score_vs_threshold)}
        </p>
      ) : null}
      <p className="text-[11px] text-muted-foreground">{data.method_text}</p>

      {data.features ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[20rem] text-left text-xs" data-testid="explanation-table">
            <caption className="sr-only">Detector inputs of the reading behind this alert, largest deviation first</caption>
            <thead>
              <tr className="text-muted-foreground">
                <th scope="col" className="py-1 pr-2 font-medium">#</th>
                <th scope="col" className="py-1 pr-2 font-medium">Signal</th>
                <th scope="col" className="py-1 pr-2 font-medium">Value</th>
                <th scope="col" className="py-1 pr-2 font-medium">Place in training range</th>
              </tr>
            </thead>
            <tbody>
              {data.features.map((f) => (
                <tr key={f.feature} data-testid="explanation-row" data-outside={f.outside_range ? "true" : "false"} className="border-t border-border align-top">
                  <td className="py-1 pr-2 font-mono tabular-nums">{f.rank}</td>
                  <td className="py-1 pr-2">{featureLabel(f.feature)}</td>
                  <td className="py-1 pr-2 font-mono tabular-nums">{f.value.toFixed(1)}</td>
                  <td className="space-y-1 py-1 pr-2">
                    <Bar position={f.position} />
                    <span className="block">{f.outside_range ? `Outside the range (${Math.round(f.outside_range_by * 100)}% of its width beyond the edge)` : `${Math.round(f.position * 100)}% of the way through`}</span>
                    <span className="block text-[11px] text-muted-foreground">{f.train_min.toFixed(1)} to {f.train_max.toFixed(1)}</span>
                    <span className="sr-only">{deviationSentence(f)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {liveForThis !== undefined ? <LiveWhy explanation={liveForThis} /> : null}

      <ul className="space-y-1 text-[11px] text-muted-foreground">
        <li>{data.threshold_basis[0].toUpperCase() + data.threshold_basis.slice(1)}.</li>
        {data.reading_origin ? <li>Reading origin: {data.reading_origin}.</li> : null}
        {data.unavailable.map((u) => (
          <li key={u} className="flex items-start gap-1" data-testid="explanation-unavailable">
            <AlertTriangle aria-hidden="true" className="mt-0.5 h-3 w-3 shrink-0" />
            {u}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * A disclosure inside the alert detail: "Why did this fire?". Nothing is requested until it is opened. The numbers are the
 * deterministic range deviation of the stored reading and the stored score against the detector threshold (synthetic-data detector).
 */
export function AlertExplanation({ alertId }: { alertId: number }) {
  const [open, setOpen] = useState(false);
  const { state, refetch } = useAlertExplanation(alertId, open);
  return (
    <section aria-label="Why did this fire" className="space-y-2" data-testid="alert-explanation">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
          className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <HelpCircle aria-hidden="true" className="h-3.5 w-3.5" />
          {open ? "Hide why this fired" : "Why did this fire?"}
        </button>
        <ModelPassportButton kind="anomaly" label="Detector passport" />
      </div>
      {open ? (
        <StateBoundary state={state} onRetry={refetch} messages={{ loading: "Computing the explanation…" }}>
          {(data) => <Body data={data} alertId={alertId} />}
        </StateBoundary>
      ) : null}
    </section>
  );
}
