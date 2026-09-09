import { useState, useEffect, useCallback, useRef } from 'react';
import { fetchState, fetchSimulation, fetchOptimized, connectWebSocket, type StateResponse } from '@/api/apiClient';

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

export interface ScenarioResult {
  pue: number;
  wue: number;
  waterL: number;
  energyKwh: number;
  co2Kg: number;
}

// Map UI cooling mode to API mode string
function coolingModeToApi(mode: CoolingMode): string {
  const map: Record<CoolingMode, string> = {
    'Auto': 'auto',
    'Evaporative': 'evaporative',
    'Closed-Loop': 'closed_loop',
    'Free Air': 'free_air',
    'Hybrid': 'hybrid',
  };
  return map[mode];
}

// Map API cooling_mode string to UI CoolingMode
function apiToCoolingMode(mode: string): CoolingMode {
  const map: Record<string, CoolingMode> = {
    'evaporative': 'Evaporative',
    'closed_loop': 'Closed-Loop',
    'free_air': 'Free Air',
    'hybrid': 'Hybrid',
    'auto': 'Auto',
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

// Map simulation response to HourlyData
function stateToHourlyData(states: StateResponse[]): HourlyData[] {
  return states.map((state, idx) => {
    const hour = idx;
    const waterPerHour = state.wue * state.it_power_kw;
    return {
      hour,
      itPower: +state.it_power_kw.toFixed(0),
      coolingPower: +state.cooling_power_kw.toFixed(0),
      temperature: +state.outside_temp_C.toFixed(1),
      waterConsumed: +waterPerHour.toFixed(1),
      coolingMode: apiToCoolingMode(state.cooling_mode),
    };
  });
}

function clamp(v: number, min: number, max: number) { return Math.max(min, Math.min(max, v)); }

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
  const waterPerHour = waterBase * (0.5 + tempFactor * 0.8) * (cfg.aiOptimizer ? 0.8 : 1) * (1 + cfg.waterStress * 0.3);
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
    const hourTemp = cfg.outsideTemp + Math.sin((h - 6) * Math.PI / 12) * 8;
    const hourUtil = cfg.serverUtil + Math.sin(h * Math.PI / 12) * 15;
    const hourCfg = { ...cfg, outsideTemp: hourTemp, serverUtil: clamp(hourUtil, 10, 100) };
    const kpi = computeKpi(hourCfg);
    const mode = cfg.coolingMode === 'Auto'
      ? (hourTemp < 15 ? 'Free Air' : hourTemp < 25 ? 'Evaporative' : 'Closed-Loop')
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

const EVENT_MESSAGES: { msg: string; type: EventItem['type'] }[] = [
  { msg: 'Cooling mode switched to Evaporative', type: 'info' },
  { msg: 'PUE target achieved: 1.28', type: 'success' },
  { msg: 'Outlet temperature warning: 32.1°C', type: 'warning' },
  { msg: 'AI optimizer adjusted chiller setpoint', type: 'info' },
  { msg: 'Water consumption spike detected', type: 'warning' },
  { msg: 'Free cooling engaged — low ambient temp', type: 'success' },
  { msg: 'Server rack A3 utilisation at 95%', type: 'warning' },
  { msg: 'Scheduled maintenance window active', type: 'info' },
  { msg: 'Anomaly detected in cooling loop B', type: 'error' },
  { msg: 'Energy savings target met for shift', type: 'success' },
];

export function useSimulation() {
  const [config, setConfig] = useState<SimConfig>({
    serverUtil: 65,
    outsideTemp: 22,
    waterStress: 0.4,
    chilledWaterSetpoint: 7,
    coolingMode: 'Auto',
    aiOptimizer: true,
  });

  const [kpi, setKpi] = useState<KpiData>(computeKpi(config));
  const [anomalyScore, setAnomalyScore] = useState(23);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [hourlyData, setHourlyData] = useState<HourlyData[]>([]);
  const [simRunning, setSimRunning] = useState(false);

  // live KPI updates
  useEffect(() => {
    const base = computeKpi(config);
    setKpi({
      ...base,
      pue: +(base.pue + (Math.random() - 0.5) * 0.02).toFixed(2),
      coolingPowerKw: +(base.coolingPowerKw + (Math.random() - 0.5) * 10).toFixed(0),
      waterPerHour: +(base.waterPerHour + (Math.random() - 0.5) * 3).toFixed(1),
    });
  }, [config]);

  // live anomaly + events ticker
  useEffect(() => {
    const interval = setInterval(() => {
      setAnomalyScore(prev => clamp(prev + (Math.random() - 0.48) * 8, 0, 100));
      if (Math.random() > 0.6) {
        const evt = EVENT_MESSAGES[Math.floor(Math.random() * EVENT_MESSAGES.length)];
        setEvents(prev => [{
          id: Date.now(),
          time: new Date().toLocaleTimeString(),
          message: evt.msg,
          type: evt.type,
        }, ...prev].slice(0, 5));
      }
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  // init events
  useEffect(() => {
    const initial = EVENT_MESSAGES.slice(0, 5).map((e, i) => ({
      id: i,
      time: new Date(Date.now() - (5 - i) * 60000).toLocaleTimeString(),
      message: e.msg,
      type: e.type,
    }));
    setEvents(initial);
  }, []);

  const runSimulation = useCallback(() => {
    setSimRunning(true);
    setTimeout(() => {
      setHourlyData(generateHourlyData(config));
      setSimRunning(false);
    }, 1500);
  }, [config]);

  const getScenarioResult = useCallback((cfg: SimConfig) => computeScenario(cfg), []);

  return { config, setConfig, kpi, anomalyScore, events, hourlyData, simRunning, runSimulation, getScenarioResult };
}
