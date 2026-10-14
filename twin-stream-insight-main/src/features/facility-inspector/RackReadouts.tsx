import { useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import type { SlotWidgetProps } from "../types";
import { fetchAlerts, type AlertRecord } from "@/api/apiClient";
import { alertsQueryKey } from "@/api/alerts";
import { StateBoundary, StateNotice } from "@/state/StateBoundary";
import { useApiQuery } from "@/state/useApiQuery";
import { useFeed } from "@/telemetry/useFeed";
import { NOT_REPORTED, requestWindow, sensorIdFor } from "@/telemetry/history/model";
import { useFacilityId, useTelemetryHistory } from "@/telemetry/history/useTelemetryHistory";
import { formatAge } from "@/provenance";
import { noDataNotice, toReadout, type LiveFeed } from "@/three/visualizationModes";
import { SparklineChart, SPARK_SIZE } from "./Sparkline";
import { HEALTH_SCORE_TEXT, SPARK_MEASURAND, SPARK_WINDOW_HOURS, buildSparkline, openAlertCount, readingRows } from "./readouts";

/** Same page size as the Incidents panel, so both share one cached query. */
const ALERTS_LIMIT = 50;

function useLiveFeed(): LiveFeed {
  const frame = useFeed((v) => v.frame);
  const freshness = useFeed((v) => v.freshness);
  const reconnectAttempt = useFeed((v) => v.transport.detail?.attempt ?? null);
  return useMemo(() => ({ frame, freshness, reconnectAttempt }), [frame, freshness, reconnectAttempt]);
}

function Heading({ children }: { children: string }) {
  return <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{children}</p>;
}

function OpenAlerts() {
  const { state, refetch } = useApiQuery<AlertRecord[]>({
    queryKey: alertsQueryKey(ALERTS_LIMIT),
    queryFn: ({ signal }) => fetchAlerts(ALERTS_LIMIT, signal),
    staleTime: 15_000,
    refetchOnWindowFocus: false,
  });
  return (
    <StateBoundary state={state} onRetry={refetch} block={false}>
      {(alerts, meta) => (
        <p data-testid="open-alerts" className="text-xs">
          <span className="font-mono text-sm text-foreground">{openAlertCount(alerts)}</span>{" "}
          <span className="text-muted-foreground">unacknowledged of the last {alerts.length} recorded{meta.refreshFailed ? " (last refresh failed)" : ""}</span>
        </p>
      )}
    </StateBoundary>
  );
}

function History() {
  // The window is fixed when it is opened or refreshed, never on a timer: the backend allows 60 requests/minute.
  const [endMs, setEndMs] = useState(() => Date.now());
  const window = useMemo(() => requestWindow(endMs, SPARK_WINDOW_HOURS), [endMs]);
  const facility = useFacilityId();
  const sensorId = facility.state.status === "ready" ? sensorIdFor(facility.state.data, SPARK_MEASURAND) : null;
  const history = useTelemetryHistory(sensorId, window);

  const body =
    facility.state.status !== "ready" ? (
      <StateBoundary state={facility.state} onRetry={facility.refetch} block={false}>
        {() => null}
      </StateBoundary>
    ) : (
      <StateBoundary
        state={history.state}
        onRetry={history.refetch}
        block={false}
        messages={{ empty: "No stored samples in the last 30 minutes." }}
      >
        {(data, meta) => {
          const model = buildSparkline(data, SPARK_SIZE.width, SPARK_SIZE.height);
          if (!model) return <StateNotice kind="empty" text="No usable samples in the last 30 minutes." block={false} />;
          const origins = [...new Set(data.items.map((i) => i.origin ?? null))];
          return (
            <div className="space-y-1">
              <SparklineChart model={model} label="Facility server outlet temperature, last 30 minutes" />
              <p className="font-mono text-[11px] text-muted-foreground">
                {model.min.toFixed(1)}–{model.max.toFixed(1)} {model.unit ?? ""} · {model.goodCount} samples
                {model.paths.length > 1 ? ` · ${model.paths.length - 1} reported gap${model.paths.length === 2 ? "" : "s"}` : ""}
              </p>
              <p className="text-[11px] text-muted-foreground">
                {model.fromLabel} → {model.toLabel} · origin: {origins.map((o) => o ?? NOT_REPORTED).join(", ")}
                {meta.refreshFailed ? " · last refresh failed, showing earlier data" : ""}
              </p>
              {model.excluded > 0 && <p className="text-[11px] text-muted-foreground">{model.excluded} samples with a non-ok quality are not drawn.</p>}
            </div>
          );
        }}
      </StateBoundary>
    );

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <Heading>Last 30 minutes</Heading>
        <button
          type="button"
          onClick={() => setEndMs(Date.now())}
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Refresh the 30-minute history"
        >
          <RefreshCw aria-hidden="true" className="h-3 w-3" /> Refresh
        </button>
      </div>
      {body}
    </div>
  );
}

function Readings({ rackId }: { rackId: string }) {
  const feed = useLiveFeed();
  const readout = toReadout(feed);
  const rows = readout.mode === "none" ? null : readingRows(readout.state);
  const lastKnown = readout.mode === "last-known";
  return (
    <section aria-label={`Live readings for ${rackId}`} data-testid="rack-readouts" className="space-y-3">
      <div className="space-y-1">
        <Heading>Live readings</Heading>
        <p className="text-[11px] text-muted-foreground" data-testid="facility-wide-note">
          Facility-wide, not specific to this rack: the backend reports no per-rack telemetry, so every rack shows the same values.
        </p>
      </div>

      {rows === null ? (
        (() => {
          const notice = noDataNotice(readout.mode === "none" ? readout.freshness : "unavailable");
          return <StateNotice kind={notice.kind} text={notice.text} block={false} />;
        })()
      ) : (
        <dl
          data-readout={readout.mode}
          className={`grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 font-mono text-xs ${lastKnown ? "rounded border border-dashed border-muted-foreground/60 p-1.5 text-muted-foreground" : "text-foreground"}`}
        >
          {readout.mode === "last-known" && (
            <p data-testid="readouts-last-known" className="col-span-2 font-sans text-[10px] uppercase tracking-wider">
              Last known · {formatAge(readout.ageMs)}
            </p>
          )}
          {rows.map((r) => (
            <div key={r.id} className="contents" data-testid={`reading-${r.id}`}>
              <dt className="font-sans text-muted-foreground">{r.label}</dt>
              <dd>{r.value}</dd>
            </div>
          ))}
        </dl>
      )}

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-muted-foreground">Health score</dt>
        <dd data-testid="health-score" className="font-mono text-foreground">
          {HEALTH_SCORE_TEXT} <span className="font-sans text-[11px] text-muted-foreground">— the backend has no per-rack health score</span>
        </dd>
        <dt className="text-muted-foreground">Open alerts</dt>
        <dd>
          <OpenAlerts />
        </dd>
      </dl>

      <History />
    </section>
  );
}

/** Slot widget (`facility-inspector`): readings for the selected rack. Nothing is rendered without a selection. */
export default function RackReadouts({ context }: SlotWidgetProps) {
  const rackId = typeof context.rackId === "string" && context.rackId !== "" ? context.rackId : null;
  if (rackId === null) return null;
  return <Readings rackId={rackId} />;
}
