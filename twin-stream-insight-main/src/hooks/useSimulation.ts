import { useState, useEffect, useCallback, useRef } from 'react';
import {
  fetchState,
  fetchSimulation,
  fetchAnomalyScore,
  connectWebSocket,
  type StateResponse,
} from '@/api/apiClient';
import { fetchEquipmentHealth, type EquipmentHealthResponse, type StateResponse } from '@/api/apiClient';

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
const [liveState, setLiveState] = useState<StateResponse | null>(null);
const [equipmentHealth, setEquipmentHealth] = useState<EquipmentHealthResponse | null>(null);

useEffect(() => {
    fetchEquipmentHealth()
      .then(setEquipmentHealth)
      .catch((e) => console.warn('[useSimulation] fetchEquipmentHealth failed:', e));
  }, []);

export interface ScenarioResult {
  pue: number;
  wue: number;
  waterL: number;
  energyKwh: number;
  co2Kg: number;
}

function clamp(v: number, min: number, max: number) {
  return Math.max(min, Math.min(max, v));
}

// Map UI cooling mode to API mode string
function coolingModeToApi(mode: CoolingMode): string {
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

// -----------------------------------------------------------------------
// NOTE ON SCOPE: the functions below (computeKpi/generateHourlyData/
// computeScenario) are the ORIGINAL local-computation fallbacks. They are
// kept ONLY to back getScenarioResult (consumed by WhatIfTab.tsx via a
// synchronous useMemo). Wiring that to real data requires also converting
// WhatIfTab.tsx to handle an async result -- deliberately left as a named
// follow-up rather than guessed at here. Every other value this hook
// returns (kpi, anomalyScore, events, hourlyData) is now backed by the
// real backend.
// -----------------------------------------------------------------------

function computeKpi(cfg: SimConfig): KpiData {
  const base = cfg.serverUtil / 100;
  const itPower = 200 + base * 800;
  const tempFactor = clamp((cfg.outsideTemp - 10) / 30, 0, 1);
  let coolingEff = 0.35 + tempFactor * 0.35;
  if (cfg.coolingMode === 'Free Air' && cfg.outsideTemp < 18) coolingEff *= 0.5;
  if (cfg.coolingMode === 'Evaporative') coolingEff *= 0.7;
  if (cfg.coolingMode === 'Hybrid') coolingEff *= 0.65;
  if (cfg.aiOptimizer) coolingEff *= 0.88;
  const coolingPower = itPower * coolingEff;
  const pue = (itPower + coolingPower + 40) / itPower;
  const waterBase = cfg.coolingMode === 'Closed-Loop' ? 5 : cfg.coolingMode === 'Free Air' ? 2 : 80;
  const waterPerHour =
    waterBase * (0.5 + tempFactor * 0.8) * (cfg.aiOptimizer ? 0.8 : 1) * (1 + cfg.waterStress * 0.3);
  const wue = waterPerHour / itPower;
  const outletTemp = cfg.chilledWaterSetpoint + 8 + tempFactor * 6 + base * 4;
  return {
    pue: +pue.toFixed(2),
    pueTrend: pue < 1.4 ? 'down' : pue > 1.6 ? 'up' : 'stable',
    wue: +wue.toFixed(3),
    itPowerKw: +itPower.toFixed(0),
    coolingPowerKw: +coolingPower.toFixed(0),
    outletTemp: +outletTemp.toFixed(1),
    waterPerHour: +waterPerHour.toFixed(1),
  };
}

function generateHourlyData(cfg: SimConfig): HourlyData[] {
  const data: HourlyData[] = [];
  for (let h = 0; h < 24; h++) {
    const hourTemp = cfg.outsideTemp + Math.sin(((h - 6) * Math.PI) / 12) * 8;
    const hourUtil = cfg.serverUtil + Math.sin((h * Math.PI) / 12) * 15;
    const hourCfg = { ...cfg, outsideTemp: hourTemp, serverUtil: clamp(hourUtil, 10, 100) };
    const kpi = computeKpi(hourCfg);
    const mode =
      cfg.coolingMode === 'Auto'
        ? hourTemp < 15
          ? 'Free Air'
          : hourTemp < 25
          ? 'Evaporative'
          : 'Closed-Loop'
        : cfg.coolingMode;
    data.push({
      hour: h,
      itPower: kpi.itPowerKw,
      coolingPower: kpi.coolingPowerKw,
      temperature: +hourTemp.toFixed(1),
      waterConsumed: +(kpi.waterPerHour * (1 + Math.random() * 0.1)).toFixed(1),
      coolingMode: mode as CoolingMode,
    });
  }
  return data;
}

function computeScenario(cfg: SimConfig): ScenarioResult {
  const hourly = generateHourlyData(cfg);
  const totalEnergy = hourly.reduce((s, d) => s + d.itPower + d.coolingPower, 0);
  const totalWater = hourly.reduce((s, d) => s + d.waterConsumed, 0);
  const avgPue = hourly.reduce((s, d) => s + (d.itPower + d.coolingPower + 40) / d.itPower, 0) / 24;
  return {
    pue: +avgPue.toFixed(2),
    wue: +(totalWater / hourly.reduce((s, d) => s + d.itPower, 0)).toFixed(3),
    waterL: +totalWater.toFixed(0),
    energyKwh: +totalEnergy.toFixed(0),
    co2Kg: +(totalEnergy * 0.4).toFixed(0),
  };
}

// A tuple of the 5 features the anomaly detector expects, in the exact
// order api/main.py's docstring specifies:
// [water_flow_lpm, water_pressure_bar, server_outlet_temp_C, it_power_kw, humidity_pct]
type AnomalyFeatureTuple = [number, number, number, number, number];

function stateToAnomalyFeatures(state: StateResponse): AnomalyFeatureTuple {
  return [
    state.water_flow_lpm,
    state.water_pressure_bar,
    state.server_outlet_temp_C,
    state.it_power_kw,
    state.humidity_pct,
  ];
}

export function useSimulation() {
  const [config, setConfig] = useState<SimConfig>({
    serverUtil: 65,
    outsideTemp: 22,
    waterStress: 0.4,
    chilledWaterSetpoint: 7,
    coolingMode: 'Auto',
    aiOptimizer: true,
  });

  // Transient initial estimate only -- replaced by the first real
  // fetchState() response below, typically within one debounce interval.
  const [kpi, setKpi] = useState<KpiData>(computeKpi(config));
  const [anomalyScore, setAnomalyScore] = useState(0);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [hourlyData, setHourlyData] = useState<HourlyData[]>([]);
  const [simRunning, setSimRunning] = useState(false);

  const prevPueRef = useRef<number | undefined>(undefined);
  const anomalyBufferRef = useRef<AnomalyFeatureTuple[]>([]);

  function pushEvent(message: string, type: EventItem['type']) {
    setEvents((prev) =>
      [{ id: Date.now(), time: new Date().toLocaleTimeString(), message, type }, ...prev].slice(0, 5)
    );
  }

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
        console.warn('[useSimulation] fetchState failed, keeping previous KPI values:', e);
        pushEvent('Live data temporarily unavailable', 'warning');
      }
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [config]);

  // Live ambient feed + anomaly detection: independent of the sliders --
  // this is the facility's actual live telemetry stream, not a
  // what-if preview. Feeds a rolling 12-reading buffer into the real
  // trained anomaly detector.
  useEffect(() => {
    const { disconnect } = connectWebSocket(async (state) => {
      setLiveState(state);
      const buf = anomalyBufferRef.current;
      buf.push(stateToAnomalyFeatures(state));
      if (buf.length > 12) buf.shift();
      anomalyBufferRef.current = buf;

      if (buf.length === 12) {
        try {
          const result = await fetchAnomalyScore(buf);
          // Normalize against the model's OWN trained threshold (95th
          // percentile of training error) rather than an invented scale --
          // score === threshold lands at 50 on the gauge, i.e. right at
          // the model's real alert boundary.
          const normalized = clamp((result.score / (result.threshold || 1)) * 50, 0, 100);
          setAnomalyScore(normalized);
          if (result.alert) {
            pushEvent(result.message, result.type === 'error' ? 'error' : 'warning');
          }
        } catch (e) {
          console.warn('[useSimulation] fetchAnomalyScore failed:', e);
        }
      }
    });
    return disconnect;
  }, []);

  const runSimulation = useCallback(() => {
    setSimRunning(true);
    fetchSimulation(24, { utilisation: config.serverUtil / 100, stress: config.waterStress })
      .then((states) => setHourlyData(stateToHourlyData(states)))
      .catch((e) => {
        console.warn('[useSimulation] fetchSimulation failed:', e);
        pushEvent('Simulation request failed', 'error');
      })
      .finally(() => setSimRunning(false));
  }, [config]);

  // NOT YET WIRED TO REAL DATA -- see the scope note above computeKpi().
  // WhatIfTab.tsx expects a synchronous (cfg) => ScenarioResult; converting
  // this to real data requires also updating that component to handle an
  // async result, which is a separate, explicitly deferred change.
  const getScenarioResult = useCallback((cfg: SimConfig) => computeScenario(cfg), []);

  return {
    config,
    setConfig,
    kpi,
    anomalyScore,
    events,
    hourlyData,
    simRunning,
    runSimulation,
    getScenarioResult,
    liveState,
    equipmentHealth,
  };
}