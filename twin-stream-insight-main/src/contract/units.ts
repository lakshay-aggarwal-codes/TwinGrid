/**
 * FE-01: unit/precision table for every numeric field the app displays.
 *
 * `source` says how much we know about the unit:
 *  - `field-name`  the unit is encoded in the backend field name (`_kw`, `_C`, `_lpm`, ...);
 *  - `documented`  stated in a backend docstring/parameter description, not in the name;
 *  - `unverified`  nobody has confirmed it. The UI must show the value WITHOUT a unit (UQ-1).
 *
 * `precision` is a display cap (decimal places), deliberately conservative: it must not imply accuracy the
 * simulator does not have.
 */

export type UnitSource = 'field-name' | 'documented' | 'unverified';

export interface UnitInfo {
  /** null = dimensionless, or unit unknown (see `source`). */
  readonly unit: string | null;
  readonly precision: number;
  readonly label: string;
  readonly source: UnitSource;
}

const u = (label: string, unit: string | null, precision: number, source: UnitSource): UnitInfo => ({
  unit,
  precision,
  label,
  source,
});

export const UNITS: Readonly<Record<string, UnitInfo>> = {
  // --- state / live frame ---
  server_utilisation: u('Server utilisation', null, 2, 'unverified'), // UQ-1: 0-1 vs 0-100 unconfirmed
  outside_temp_C: u('Outside temperature', '°C', 1, 'field-name'),
  server_inlet_temp_C: u('Server inlet temperature', '°C', 1, 'field-name'),
  server_outlet_temp_C: u('Server outlet temperature', '°C', 1, 'field-name'),
  it_power_kw: u('IT power', 'kW', 1, 'field-name'),
  cooling_power_kw: u('Cooling power', 'kW', 1, 'field-name'),
  total_power_kw: u('Total facility power', 'kW', 1, 'field-name'),
  pue: u('PUE', null, 2, 'documented'), // dimensionless ratio
  water_flow_lpm: u('Water flow', 'L/min', 1, 'field-name'),
  water_consumed_L: u('Water consumed', 'L', 1, 'field-name'),
  wue: u('WUE', 'L/kWh', 2, 'documented'), // litres per IT kWh (twin_service docstring)
  humidity_pct: u('Humidity', '%', 0, 'field-name'),
  water_pressure_bar: u('Water pressure', 'bar', 2, 'field-name'),
  anomaly: u('Twin anomaly flag (0/1)', null, 0, 'documented'),
  water_stress: u('Water stress index', null, 2, 'documented'), // [0-1] per request-parameter docs
  carbon_intensity_gco2_per_kwh: u('Grid carbon intensity', 'gCO₂/kWh', 0, 'field-name'),
  carbon_gco2: u('Carbon emitted', 'gCO₂', 0, 'field-name'),
  // --- live timing ---
  sim_time_scale: u('Simulated seconds per wall second', null, 1, 'documented'),
  interval_s: u('Broadcast interval', 's', 1, 'field-name'),
  // --- whatif ---
  hours: u('Scenario length', 'h', 0, 'field-name'),
  mean_pue: u('Mean PUE', null, 2, 'documented'),
  total_water_L: u('Total water', 'L', 0, 'field-name'),
  total_energy_kwh: u('Total energy', 'kWh', 0, 'field-name'),
  total_co2_kg: u('Total CO₂', 'kg', 1, 'field-name'),
  max_outlet_temp_C: u('Maximum outlet temperature', '°C', 1, 'field-name'),
  // --- optimize summary ---
  mean_wue: u('Mean WUE', 'L/kWh', 2, 'documented'),
  mean_cooling_power_kw: u('Mean cooling power', 'kW', 1, 'field-name'),
  total_water_consumed_L: u('Total water consumed', 'L', 0, 'field-name'),
  total_reward: u('Total reward (optimiser objective)', null, 2, 'documented'),
  safety_violations: u('Safety violations (count)', null, 0, 'documented'),
  // --- anomaly pipeline / alert ---
  score: u('Anomaly reconstruction error', null, 3, 'documented'),
  threshold: u('Detector threshold', null, 3, 'documented'),
  // --- equipment health (methodology metrics on a PROXY dataset; units of mae/rmse are not stated by the backend) ---
  mae_improvement_pct: u('MAE improvement over baseline', '%', 1, 'field-name'),
  mae: u('Mean absolute error', null, 2, 'unverified'),
  rmse: u('Root mean squared error', null, 2, 'unverified'),
  r2: u('R²', null, 2, 'documented'),
  // --- facility geometry: unit is facility.frame_unit, not a constant ---
  x: u('X position', null, 2, 'documented'),
  y: u('Y position', null, 2, 'documented'),
  z: u('Z position', null, 2, 'documented'),
  rotation_deg: u('Rotation', '°', 0, 'field-name'),
};

export function unitFor(field: string): UnitInfo | undefined {
  return Object.prototype.hasOwnProperty.call(UNITS, field) ? UNITS[field] : undefined;
}
