import { reportError } from '@/lib/errorReporter.ts';
import { useState, useEffect, useCallback, useRef, useSyncExternalStore } from 'react';
import {
  fetchState,
  fetchSimulation,
  fetchEquipmentHealth,
  type AnomalyStatusPayload,
  type EquipmentHealthResponse,
  type LiveStatePayload,
  type StateResponse,
} from '@/api/apiClient.ts';
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

export interface KpiData {
  pue: number;
  pueTrend: 'up' | 'down' | 'stable';
  wue: number;
  itPowerKw: number;
  coolingPowerKw: number;
  outletTemp: number;
  waterPerHour: number;
}

export interface LatestAnomaly {
  type: string;
  message: string;
}

export interface HourlyData {
  hour: number;
  itPower: number;
  coolingPower: number;
  temperature: number;
  waterConsumed: number;
  coolingMode: CoolingMode;
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

// Map API cooling_mode string to UI CoolingMode
function apiToCoolingMode(mode: string): CoolingMode {
  const map: Record<string, CoolingMode> = {
    evaporative: 'Evaporative',
    closed_loop: 'Closed-Loop',
    free_air: 'Free Air',
    hybrid: 'Hybrid',
    auto: 'Auto',
  };
  return map[mode] || 'Auto';
}

// Map API state to KpiData
function stateToKpi(state: StateResponse, prevPue?: number): KpiData {
  const waterPerHour = state.wue * state.it_power_kw; // L/kWh * kW = L/h
  let pueTrend: 'up' | 'down' | 'stable' = 'stable';
  if (prevPue !== undefined) {
    if (state.pue < prevPue - 0.01) pueTrend = 'down';
    else if (state.pue > prevPue + 0.01) pueTrend = 'up';
  }
  return {
    pue: +state.pue.toFixed(2),
    pueTrend,
    wue: +state.wue.toFixed(3),
    itPowerKw: +state.it_power_kw.toFixed(0),
    coolingPowerKw: +state.cooling_power_kw.toFixed(0),
    outletTemp: +state.server_outlet_temp_C.toFixed(1),
    waterPerHour: +waterPerHour.toFixed(1),
  };
}

// Map API simulation response to HourlyData
function stateToHourlyData(states: StateResponse[]): HourlyData[] {
  return states.map((state, idx) => {
    const waterPerHour = state.wue * state.it_power_kw;
    return {
      hour: idx,
      itPower: +state.it_power_kw.toFixed(0),
      coolingPower: +state.cooling_power_kw.toFixed(0),
      temperature: +state.outside_temp_C.toFixed(1),
      waterConsumed: +waterPerHour.toFixed(1),
      coolingMode: apiToCoolingMode(state.cooling_mode),
    };
  });
}

// Shown until the first real /api/state response arrives. Deliberately zeros,
// not an estimate: no number on the dashboard is ever computed locally.
const EMPTY_KPI: KpiData = {
  pue: 0,
  pueTrend: 'stable',
  wue: 0,
  itPowerKw: 0,
  coolingPowerKw: 0,
  outletTemp: 0,
  waterPerHour: 0,
};

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

  const [kpi, setKpi] = useState<KpiData>(EMPTY_KPI);
  const liveState = useFeed(selectLegacyLiveState, Object.is, feed);
  const liveness = useFeed(selectLegacyLiveness, Object.is, feed);
  const adapter: DeprecatedLiveAdapter = { liveState, liveness };
  const [equipmentHealth, setEquipmentHealth] = useState<EquipmentHealthResponse | null>(null);
  const [anomalyScore, setAnomalyScore] = useState(0);
  const [latestAnomaly, setLatestAnomaly] = useState<LatestAnomaly | null>(null);
  const events = useSyncExternalStore(feed.events.subscribe, feed.events.getSnapshot);
  const [hourlyData, setHourlyData] = useState<HourlyData[]>([]);
  const [simRunning, setSimRunning] = useState(false);

  const prevPueRef = useRef<number | undefined>(undefined);
  // Server-owned anomaly pipeline result (backend T3). The browser no longer scores anything.
  const [anomalyStatus, setAnomalyStatus] = useState<AnomalyStatusPayload | null>(null);
  const lastEpisodeKeyRef = useRef<string | null>(null);
  const lastAnomalyStatusRef = useRef<string | null>(null);

  const pushEvent = feed.events.push;

  useEffect(() => {
    let cancelled = false;
    fetchEquipmentHealth()
      .then((health) => {
        if (!cancelled) setEquipmentHealth(health);
      })
      .catch((e) => reportError('useSimulation.fetchEquipmentHealth', e, 'warning'));
    return () => {
      cancelled = true;
    };
  }, []);

  // KPI cards: driven by the sliders. Debounced real fetchState() call --
  // this is "what would this configuration produce right now", answered
  // by the actual physics twin, not a local formula.
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const state = await fetchState({
          utilisation: config.serverUtil / 100,
          outside_temp: config.outsideTemp,
          water_stress: config.waterStress,
          mode: coolingModeToApi(config.coolingMode),
        });
        if (cancelled) return;
        setKpi(stateToKpi(state, prevPueRef.current));
        prevPueRef.current = state.pue;
      } catch (e) {
        reportError('useSimulation.fetchState', e, 'warning');
        pushEvent('Live data temporarily unavailable', 'warning');
      }
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [config]);

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
    setSimRunning(true);
    fetchSimulation(24, {
      utilisation: config.serverUtil / 100,
      outside_temp: config.outsideTemp,
      stress: config.waterStress,
    })
      .then((states) => setHourlyData(stateToHourlyData(states)))
      .catch((e) => {
        reportError('useSimulation.fetchSimulation', e, 'warning');
        pushEvent('Simulation request failed', 'error');
      })
      .finally(() => setSimRunning(false));
  }, [config]);

  return {
    config,
    setConfig,
    kpi,
    anomalyScore,
    latestAnomaly,
    anomalyStatus,
    events,
    hourlyData,
    simRunning,
    runSimulation,
    ...adapter,
    equipmentHealth,
  };
}
