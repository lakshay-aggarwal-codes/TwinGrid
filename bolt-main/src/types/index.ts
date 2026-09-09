export interface SimulationData {
  pue: number;
  wue: number;
  it_power_kw: number;
  cooling_power_kw: number;
  water_consumed_L: number;
  outlet_temp: number;
  cooling_mode: 'free_air' | 'closed_loop' | 'evaporative';
  timestamp?: number;
  hour?: number;
}

export interface OptimizeRequest {
  alpha: number;
  beta: number;
  gamma: number;
  water_stress: number;
}

export interface OptimizeResponse {
  recommended_action: {
    utilisation: number;
    cooling_mode: string;
    inlet_temp: number;
    pue: number;
    wue: number;
    water_consumed_L: number;
    score: number;
  };
  message: string;
}
