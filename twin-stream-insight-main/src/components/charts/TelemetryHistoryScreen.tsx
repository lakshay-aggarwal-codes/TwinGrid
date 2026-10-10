import { useMemo } from 'react';
import { StateBoundary, StateNotice } from '@/state/StateBoundary';
import { MEASURANDS, WINDOWS, requestWindow, sensorIdFor } from '@/telemetry/history/model';
import { useFacilityId, useTelemetryHistory } from '@/telemetry/history/useTelemetryHistory';
import { HistoryView } from './HistoryView';

export interface TelemetryHistoryScreenProps {
  measurand: string;
  hours: number;
  /** End of the requested window, epoch ms. The page captures it when the window changes or the person refreshes. */
  windowEndMs: number;
  onMeasurandChange: (id: string) => void;
  onHoursChange: (hours: number) => void;
  onRefreshWindow: () => void;
}

function HistoryPanel({ sensorId, hours, windowEndMs }: { sensorId: string; hours: number; windowEndMs: number }) {
  const window = useMemo(() => requestWindow(windowEndMs, hours), [windowEndMs, hours]);
  const { state, refetch } = useTelemetryHistory(sensorId, window);
  if (state.status === 'error' && state.kind === 'not_found') {
    return <StateNotice kind="unavailable" title="Sensor not registered" text="Sensor not registered on this backend." />;
  }
  return (
    <StateBoundary state={state} onRetry={refetch} messages={{ empty: 'No stored telemetry for this window.' }}>
      {(data) => <HistoryView data={data} window={window} />}
    </StateBoundary>
  );
}

/**
 * Telemetry history: fetched when the sensor or window changes or on an explicit refresh, never on a timer
 * (the telemetry read API allows 60 requests/minute). Browser time only sets the REQUESTED window; it is never data time.
 */
export function TelemetryHistoryScreen(props: TelemetryHistoryScreenProps) {
  const facility = useFacilityId();
  const label = 'rounded border border-border bg-background px-2 py-1 text-xs text-foreground';
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Measurand
          <select className={label} value={props.measurand} onChange={(e) => props.onMeasurandChange(e.target.value)}>
            {MEASURANDS.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label} ({m.id})
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Window
          <select className={label} value={props.hours} onChange={(e) => props.onHoursChange(Number(e.target.value))}>
            {WINDOWS.map((w) => (
              <option key={w.hours} value={w.hours}>
                {w.label}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className={`${label} hover:bg-muted`} onClick={props.onRefreshWindow}>
          Refresh window
        </button>
      </div>
      <StateBoundary state={facility.state} onRetry={facility.refetch}>
        {(facilityId) => <HistoryPanel sensorId={sensorIdFor(facilityId, props.measurand)} hours={props.hours} windowEndMs={props.windowEndMs} />}
      </StateBoundary>
    </div>
  );
}
