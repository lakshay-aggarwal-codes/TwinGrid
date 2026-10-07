import type { WhatIfResponse } from "@/api/apiClient";

/** Schema-shaped what-if payload for unit tests (synthetic: tests the UI, not the backend). */
export const whatIf = (over: Partial<WhatIfResponse> = {}): WhatIfResponse => ({
  hours: 24,
  basis: "24h constant inputs",
  mean_pue: 1.31,
  wue: 0.52,
  total_water_L: 1200,
  total_energy_kwh: 5000,
  total_co2_kg: 2375,
  max_outlet_temp_C: 38.2,
  final_cooling_mode: "hybrid",
  drought_override_active: false,
  carbon_data_is_real: false,
  ...over,
});
