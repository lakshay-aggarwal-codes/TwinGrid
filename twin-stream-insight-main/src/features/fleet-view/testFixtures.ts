import type { Fleet, Site } from "./schema";

/** SYNTHETIC stand-in for the backend: five sites with known, distinct ranks so ordering assertions are exact. */
const site = (id: string, n: number, pue: number, carbon: number, alerts: number, ranks: [number, number, number], overall: number): Site => ({
  id,
  name: `Simulated site ${n}`,
  climate: `Climate ${n}`,
  inputs: { utilisation: 0.5 + n / 20, outside_temp_C: 10 + n * 5, water_stress: 0.1 },
  pue,
  wue: 1,
  cooling_mode: "hybrid",
  total_power_kw: 500,
  server_outlet_temp_C: 33,
  carbon_gco2_per_step: carbon,
  alert_conditions: alerts,
  alert_condition_names: alerts ? ["drought_override"] : [],
  rank: { pue: ranks[0], carbon_gco2_per_step: ranks[1], alert_conditions: ranks[2] },
  rank_sum: ranks[0] + ranks[1] + ranks[2],
  overall_rank: overall,
});

export const FLEET: Fleet = {
  simulated: true,
  label: "Simulated sites: the digital twin run under five different parameter sets. Not real facilities.",
  alert_note: "Alert conditions are rule checks on the simulated state, not recorded alerts.",
  carbon_data_is_real: false,
  carbon_note: "Carbon uses a flat assumed grid intensity (no carbon data file), so carbon differences between sites reflect energy use only, not different grids.",
  carbon_unit: "gCO2 per 5-minute step",
  sites: [
    site("sim-a", 1, 1.2, 100, 0, [1, 2, 1], 1),
    site("sim-b", 2, 1.3, 90, 1, [4, 1, 5], 5),
    site("sim-c", 3, 1.25, 120, 0, [3, 3, 1], 3),
    site("sim-d", 4, 1.22, 130, 0, [2, 4, 1], 2),
    site("sim-e", 5, 1.4, 140, 0, [5, 5, 1], 4),
  ],
};
