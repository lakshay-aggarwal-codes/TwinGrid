/**
 * Task 16 test fixtures.
 *
 * REAL: `REAL_WHATIF_*` are the unmodified outputs of `api.services.twin_service.compute_whatif` on this repo, captured
 * with the arguments in each name. The twin's internal IT energy for each (summed per step, not exposed by the API) was
 * 9480.000000000005 kWh and 8400.00000000003 kWh, equal to total_water_L / wue.
 *
 * SYNTHETIC: `liveSamples` builds artificial live samples with obviously round numbers. They are not backend output.
 */
import type { WhatIfResponse } from "@/api/apiClient";
import type { LiveSample } from "./liveSeries";

export const REAL_WHATIF_065_22_04_AUTO_7: WhatIfResponse = {
  hours: 24,
  basis: "24h at constant inputs, isolated digital-twin run (no RL optimizer applied)",
  inputs: { utilisation: 0.65, outside_temp_C: 22, water_stress: 0.4, mode: "auto", chilled_water_temp_C: 7 },
  mean_pue: 1.321550439044979,
  wue: 0.959936814485056,
  total_water_L: 9100.201001318335,
  total_energy_kwh: 12528.29816214626,
  total_co2_kg: 5950.941627019469,
  max_outlet_temp_C: 36.73735821275013,
  final_cooling_mode: "hybrid",
  drought_override_active: false,
  carbon_data_is_real: false,
};

export const REAL_WHATIF_05_30_02_CLOSED_9: WhatIfResponse = {
  hours: 24,
  basis: "24h at constant inputs, isolated digital-twin run (no RL optimizer applied)",
  inputs: { utilisation: 0.5, outside_temp_C: 30, water_stress: 0.2, mode: "closed_loop", chilled_water_temp_C: 9 },
  mean_pue: 1.2934905268595158,
  wue: 0.07142814944781745,
  total_water_L: 599.9964553616686,
  total_energy_kwh: 10865.320425620022,
  total_co2_kg: 5161.027202169477,
  max_outlet_temp_C: 35.696072483112886,
  final_cooling_mode: "closed_loop",
  drought_override_active: false,
  carbon_data_is_real: false,
};

export const T0 = Date.UTC(2026, 9, 15, 10, 0, 0);

/** SYNTHETIC. `n` samples, `stepMs` apart, each field a function of the index. */
export function liveSamples(
  n: number,
  fn: (i: number) => Partial<Omit<LiveSample, "t" | "seq">> = () => ({}),
  stepMs = 3000,
  startSeq: number | null = 1,
): LiveSample[] {
  return Array.from({ length: n }, (_, i) => ({
    t: T0 + i * stepMs,
    seq: startSeq === null ? null : startSeq + i,
    pue: 1.25,
    itKw: 400,
    coolingKw: 100,
    totalKw: 500,
    outletC: 30,
    carbonGPerKwh: 475,
    carbonReal: false,
    ...fn(i),
  }));
}
