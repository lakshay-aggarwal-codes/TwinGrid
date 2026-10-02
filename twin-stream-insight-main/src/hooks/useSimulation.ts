import { reportError } from '@/lib/errorReporter.ts';
import { useState, useEffect, useCallback, useRef } from 'react';
import {
  fetchState,
  fetchSimulation,
  fetchEquipmentHealth,
  connectWebSocket,
  type AnomalyStatusPayload,
  type EquipmentHealthResponse,
  type LiveStatePayload,
  type SocketStatus,
  type StateResponse,
} from '@/api/apiClient';
import {
  LIVENESS_CHECK_INTERVAL_MS,
  deriveLiveness,
  staleAfterMs,
  type LivenessStatus,
} from '@/hooks/liveness';

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

export interface EventItem {
  id: number;
  time: string;
  message: string;
  type: 'info' | 'warning' | 'success' | 'error';
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

export function useSimulation() {
  const [config, setConfig] = useState<SimConfig>({
    serverUtil: 65,
    outsideTemp: 22,
    waterStress: 0.4,
    chilledWaterSetpoint: 7,
    coolingMode: 'Auto',
    aiOptimizer: true,
  });

  const [kpi, setKpi] = useState<KpiData>(EMPTY_KPI);
  const [liveState, setLiveState] = useState<LiveStatePayload | null>(null);
  // Liveness (T1a): from socket state + wall time of the last payload, never from sim_time.
  const [liveness, setLiveness] = useState<LivenessStatus>('connecting');
  const socketStatusRef = useRef<SocketStatus>('connecting');
  const lastMessageAtRef = useRef<number | null>(null);
  const staleWindowMsRef = useRef<number>(staleAfterMs());
  const [equipmentHealth, setEquipmentHealth] = useState<EquipmentHealthResponse | null>(null);
  const [anomalyScore, setAnomalyScore] = useState(0);
  const [latestAnomaly, setLatestAnomaly] = useState<LatestAnomaly | null>(null);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [hourlyData, setHourlyData] = useState<HourlyData[]>([]);
  const [simRunning, setSimRunning] = useState(false);

  const prevPueRef = useRef<number | undefined>(undefined);
  // Server-owned anomaly pipeline result (backend T3). The browser no longer scores anything.
  const [anomalyStatus, setAnomalyStatus] = useState<AnomalyStatusPayload | null>(null);
  const lastEpisodeKeyRef = useRef<string | null>(null);
  const lastAnomalyStatusRef = useRef<string | null>(null);

  function pushEvent(message: string, type: EventItem['type']) {
    setEvents((prev) =>
      [{ id: Date.now(), time: new Date().toLocaleTimeString(), message, type }, ...prev].slice(0, 5)
    );
  }

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

  const refreshLiveness = useCallback(() => {
    const next = deriveLiveness({
      socket: socketStatusRef.current,
      lastMessageAt: lastMessageAtRef.current,
      now: Date.now(),
      staleAfterMs: staleWindowMsRef.current,
    });
    // Same value -> same state -> no re-render of every consumer once a second.
    setLiveness((prev) => (prev === next ? prev : next));
  }, []);

  // Between payloads nothing else triggers a render, so re-evaluate on a timer.
  useEffect(() => {
    const id = setInterval(refreshLiveness, LIVENESS_CHECK_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refreshLiveness]);

  // Live ambient feed: independent of the sliders -- this is the facility's live telemetry stream,
  // not a what-if preview. Anomaly detection is SERVER-owned (backend T3): each payload carries
  // `anomaly_status`, computed once per tick from the server-held 12-sample window. The browser
  // sends nothing and scores nothing.
  useEffect(() => {
    const { disconnect } = connectWebSocket(
      (state) => {
        lastMessageAtRef.current = Date.now();
        staleWindowMsRef.current = staleAfterMs(state.interval_s);
        setLiveState(state);
        refreshLiveness();

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
      },
      (status) => {
        socketStatusRef.current = status;
        refreshLiveness();
      }
    );
    return disconnect;
  }, [refreshLiveness]);

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
    liveState,
    liveness,
    equipmentHealth,
  };
}
