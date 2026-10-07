/** Minimal schema-valid payloads for FE-02 unit tests. Synthetic: they test the transport, not backend behaviour. */
export const validState = (over: Record<string, unknown> = {}) => ({
  timestamp: '2026-01-01T00:00:00',
  server_utilisation: 0.5,
  outside_temp_C: 20,
  server_inlet_temp_C: 24,
  server_outlet_temp_C: 34,
  it_power_kw: 100,
  cooling_power_kw: 20,
  total_power_kw: 120,
  pue: 1.2,
  water_flow_lpm: 50,
  water_consumed_L: 10,
  wue: 0.5,
  humidity_pct: 40,
  water_pressure_bar: 2,
  cooling_mode: 'free_air',
  anomaly: 0,
  ...over,
});

export const validAlert = (over: Record<string, unknown> = {}) => ({
  id: 1,
  created_at: '2026-01-01T00:00:00',
  type: 'thermal',
  message: 'm',
  severity: 'WARNING',
  score: 0.9,
  alert: true,
  acknowledged: false,
  acknowledged_by: null,
  acknowledged_at: null,
  ...over,
});
