import { reportError } from '@/lib/errorReporter.ts';
import { useState, useEffect, useCallback, useRef, useSyncExternalStore } from 'react';
import {
  fetchState,
  fetchSimulation,
  type AnomalyStatusPayload,
  type LiveStatePayload,
  type StateResponse,
} from '@/api/apiClient';
import { unitFor } from '@/contract/units';
import { dataStateFromError, type DataState } from '@/state/dataState';
import type { LivenessStatus } from '@/hooks/liveness';
import type { FeedStore, FeedView } from '@/telemetry/feedStore';
import { toLegacyLiveness } from '@/telemetry/freshness';
import { useFeed } from '@/telemetry/useFeed';
import type { EventItem } from '@/telemetry/eventStore';

export type { EventItem };

export type CoolingMode = 'Auto' | 'Evaporative' | 'Closed-Loop' | 'Free Air' | 'Hybrid';

export interface SimConfig {
  serverUtil: number;
  outsideTemp: number;
  waterStress: number;
  chilledWaterSetpoint: number;
  coolingMode: CoolingMode;
  aiOptimizer: boolean;
}

/**
 * FE-08: the sidebar settings a PREVIEW or run was computed for. A value never travels without these, so a result can
 * never be shown next to inputs it was not computed from.
 */
export interface PreviewInputs {
  /** Percent, as shown on the slider (sent to the backend as a 0-1 fraction). */
  utilisationPct: number;
  outsideTempC: number;
  /** Water stress index as set on the slider. */
  waterStress: number;
  coolingMode: CoolingMode;
}

/** Backend fields of one GET /api/state response, unrounded and uncomputed. Display precision comes from the unit table. */
export interface KpiData {
  pue: number;
  wue: number;
  itPowerKw: number;
  coolingPowerKw: number;
  outletTempC: number;
  waterFlowLpm: number;
}

/** FE-08: a preview KPI set: backend values plus the endpoint class and the inputs it answers for. Never feed data. */
export interface PreviewKpi {
  value: KpiData;
  provenance: { kind: 'preview'; inputs: PreviewInputs };
}

export interface LatestAnomaly {
  type: string;
  message: string;
}

/** Inputs of a GET /api/simulate run. Utilisation and outside temperature are the run's MEANS (the backend builds a diurnal curve around them). */
export interface SimInputs {
  hours: number;
  meanUtilisationPct: number;
  meanOutsideTempC: number;
  waterStress: number;
}

/** One backend step of GET /api/simulate. Every field is a backend field as provided; `coolingMode` is the raw backend string. */
export interface HourlyData {
  /** Index of the step from the start of the simulated run. Not a clock hour. */
  step: number;
  itPowerKw: number;
  coolingPowerKw: number;
  outsideTempC: number;
  /** Backend `water_consumed_L`, as reported (a running total on the twin). Never summed or derived here. */
  waterConsumedL: number;
  pue: number;
  coolingMode: string;
}

/** Number of simulated steps requested for a run. */
const SIM_HOURS = 24;

/** Format a backend number to the display precision in the FE-01 unit table (no precision claim for unknown fields). */
export function formatBackendNumber(field: string, value: number): string {
  const info = unitFor(field);
  return info ? value.toFixed(info.precision) : String(value);
}

function clamp(v: number, min: number, max: number) {
  return Math.max(min, Math.min(max, v));
}

// Map UI cooling mode to API mode string
export function coolingModeToApi(mode: CoolingMode): string {
  const map: Record<CoolingMode, string> = {
    Auto: 'auto',
    Evaporative: 'evaporative',
    'Closed-Loop': 'closed_loop',
    'Free Air': 'free_air',
    Hybrid: 'hybrid',
  };
  return map[mode];
}

// Map API state to a preview KPI. Values are the backend's, unrounded; nothing is computed here.
function stateToPreview(state: StateResponse, inputs: PreviewInputs): PreviewKpi {
  return {
    value: {
      pue: state.pue,
      wue: state.wue,
      itPowerKw: state.it_power_kw,
      coolingPowerKw: state.cooling_power_kw,
      outletTempC: state.server_outlet_temp_C,
      waterFlowLpm: state.water_flow_lpm,
    },
    provenance: { kind: 'preview', inputs },
  };
}

// Map the API simulation response to per-step rows. One backend field per column; no derivations, and the backend
// cooling mode is passed through verbatim (an unrecognised value stays unrecognised).
function stateToHourlyData(states: StateResponse[]): HourlyData[] {
  return states.map((state, step) => ({
    step,
    itPowerKw: state.it_power_kw,
    coolingPowerKw: state.cooling_power_kw,
    outsideTempC: state.outside_temp_C,
    waterConsumedL: state.water_consumed_L,
    pue: state.pue,
    coolingMode: state.cooling_mode,
  }));
}

/**
 * FE-04 TEMPORARY ADAPTER. Components still read these two fields; they migrate to `useFeed(...)` / `Stamped` in
 * FE-06/07/08/09/10, which then delete this interface. `liveState` is a BARE frame with no freshness or provenance,
 * which is exactly what the store forbids -- do not add new uses.
 */
export interface DeprecatedLiveAdapter {
  /** @deprecated Use `useFeed((v) => v.frame)` (a `Stamped` value). Removed in FE-06. */
  liveState: LiveStatePayload | null;
  /** @deprecated Use `useFeed((v) => v.freshness)`. Removed in FE-06. */
  liveness: LivenessStatus;
}

const selectLegacyLiveState = (v: FeedView): LiveStatePayload | null => v.frame?.value ?? null;
const selectLegacyLiveness = (v: FeedView): LivenessStatus => toLegacyLiveness(v.freshness.state);

/** The live feed itself (socket, freshness, seq, events) lives in `feed` (FE-04); this hook adds the slider/KPI/anomaly UI state. */
export function useSimulation(feed: FeedStore) {
  const [config, setConfig] = useState<SimConfig>({
    serverUtil: 65,
    outsideTemp: 22,
    waterStress: 0.4,
    chilledWaterSetpoint: 7,
    coolingMode: 'Auto',
    aiOptimizer: true,
  });

  // FE-08: before the first /api/state response there is NO value (never 0); a failure is an explicit state.
  const [previewKpi, setPreviewKpi] = useState<DataState<PreviewKpi>>({ status: 'loading' });
  const [previewRetry, setPreviewRetry] = useState(0);
  const liveState = useFeed(selectLegacyLiveState, Object.is, feed);
  const liveness = useFeed(selectLegacyLiveness, Object.is, feed);
  const adapter: DeprecatedLiveAdapter = { liveState, liveness };
  const [anomalyScore, setAnomalyScore] = useState(0);
  const [latestAnomaly, setLatestAnomaly] = useState<LatestAnomaly | null>(null);
  const events = useSyncExternalStore(feed.events.subscribe, feed.events.getSnapshot);
  const [hourlyData, setHourlyData] = useState<HourlyData[]>([]);
  const [simRunning, setSimRunning] = useState(false);
  const [simInputs, setSimInputs] = useState<SimInputs | null>(null);
  const [simError, setSimError] = useState(false);

  // Server-owned anomaly pipeline result (backend T3). The browser no longer scores anything.
  const [anomalyStatus, setAnomalyStatus] = useState<AnomalyStatusPayload | null>(null);
  const lastEpisodeKeyRef = useRef<string | null>(null);
  const lastAnomalyStatusRef = useRef<string | null>(null);

  const pushEvent = feed.events.push;

  // KPI cards: driven by the sliders. A debounced, abortable fetchState() -- "what would this configuration produce",
  // answered by the actual physics twin, not a local formula. Only the four inputs /api/state takes trigger it.
  const { serverUtil, outsideTemp, waterStress, coolingMode } = config;
  useEffect(() => {
    const controller = new AbortController();
    const inputs: PreviewInputs = { utilisationPct: serverUtil, outsideTempC: outsideTemp, waterStress, coolingMode };
    const timer = setTimeout(async () => {
      try {
        const state = await fetchState(
          {
            utilisation: serverUtil / 100,
            outside_temp: outsideTemp,
            water_stress: waterStress,
            mode: coolingModeToApi(coolingMode),
          },
          controller.signal
        );
        if (controller.signal.aborted) return;
        setPreviewKpi({ status: 'ready', data: stateToPreview(state, inputs) });
      } catch (e) {
        if (controller.signal.aborted) return;
        reportError('useSimulation.fetchState', e, 'warning');
        // Keep the last good preview, labelled stale (it still carries the inputs it was computed for); with no
        // previous result the failure itself is the state.
        setPreviewKpi((prev) =>
          prev.status === 'ready' ? { ...prev, freshness: 'stale', refreshFailed: true } : dataStateFromError(e)
        );
        pushEvent('Preview request failed', 'warning');
      }
    }, 300);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [serverUtil, outsideTemp, waterStress, coolingMode, previewRetry, pushEvent]);

  const retryPreview = useCallback(() => {
    setPreviewKpi({ status: 'loading' });
    setPreviewRetry((n) => n + 1);
  }, []);

  // Anomaly handling. The anomaly state arrives INSIDE the same frame as everything else (`anomaly_status`);
  // detection is SERVER-owned (backend T3): the browser sends nothing and scores nothing. The feed store calls this
  // once per accepted frame (duplicates are dropped there), so an episode can never be skipped by render batching.
  useEffect(() => {
    return feed.onFrame(({ value: state }) => {
      const a = state.anomaly_status;
      if (!a) return; // older backend: no anomaly information, never invent a "normal"
      setAnomalyStatus(a);
      const scored = a.status === 'ok' || a.status === 'anomalous';
      // Normalize against the model's OWN trained threshold: score === threshold lands at 50.
      // Not scored (warming up / unavailable / error) shows 0 on the gauge -- the status itself,
      // not this number, says why.
      setAnomalyScore(
        scored && a.score !== null && a.threshold !== null ? clamp((a.score / (a.threshold || 1)) * 50, 0, 100) : 0
      );
      // One event per anomaly EPISODE (the server's dedupe key), not per tick.
      const key = a.episode?.dedupe_key ?? null;
      if (a.status === 'anomalous' && key && key !== lastEpisodeKeyRef.current) {
        lastEpisodeKeyRef.current = key;
        pushEvent(a.message, 'warning');
        setLatestAnomaly({ type: a.type ?? 'unknown', message: a.message });
      }
      // Fail-closed states are surfaced once per transition, not every tick.
      if ((a.status === 'unavailable' || a.status === 'error') && lastAnomalyStatusRef.current !== a.status) {
        pushEvent(a.message, 'error');
      }
      lastAnomalyStatusRef.current = a.status;
    });
  }, [feed, pushEvent]);

  const runSimulation = useCallback(() => {
    const inputs: SimInputs = {
      hours: SIM_HOURS,
      meanUtilisationPct: serverUtil,
      meanOutsideTempC: outsideTemp,
      waterStress,
    };
    setSimRunning(true);
    setSimError(false);
    fetchSimulation(SIM_HOURS, {
      utilisation: serverUtil / 100,
      outside_temp: outsideTemp,
      stress: waterStress,
    })
      .then((states) => {
        setHourlyData(stateToHourlyData(states));
        setSimInputs(inputs);
      })
      .catch((e) => {
        reportError('useSimulation.fetchSimulation', e, 'warning');
        pushEvent('Simulation request failed', 'error');
        setSimError(true);
      })
      .finally(() => setSimRunning(false));
  }, [serverUtil, outsideTemp, waterStress, pushEvent]);

  return {
    config,
    setConfig,
    previewKpi,
    retryPreview,
    anomalyScore,
    latestAnomaly,
    anomalyStatus,
    events,
    hourlyData,
    simInputs,
    simError,
    simRunning,
    runSimulation,
    ...adapter,
  };
}
