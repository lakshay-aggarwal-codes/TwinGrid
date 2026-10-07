/** GET /api/state, each element of GET /api/simulate/{hours}, and the base of every /ws/live frame. */
import { z } from 'zod';
import { isoString, lenientEnum, num } from './common';

/** Backend CoolingMode enum values (src/digital_twin.py). `auto` is a request value, never a response value. */
export const CoolingMode = lenientEnum(['free_air', 'closed_loop', 'evaporative', 'hybrid'] as const);

export const StateResponse = z
  .object({
    // Always present in DigitalTwinState.to_dict(): required.
    timestamp: isoString, // SIMULATED clock, offset-less; interpret with parseInstant(..., 'sim')
    server_utilisation: num, // unit unverified (UQ-1), see units.ts
    outside_temp_C: num,
    server_inlet_temp_C: num,
    server_outlet_temp_C: num,
    it_power_kw: num,
    cooling_power_kw: num,
    total_power_kw: num,
    pue: num,
    water_flow_lpm: num,
    water_consumed_L: num,
    wue: num,
    humidity_pct: num,
    water_pressure_bar: num,
    cooling_mode: CoolingMode,
    anomaly: num, // the twin's own 0/1 flag; NOT the anomaly pipeline (see anomaly_status)
    // Additive / environment-dependent: optional, never defaulted.
    water_stress: num.optional(),
    carbon_intensity_gco2_per_kwh: num.optional(),
    carbon_gco2: num.optional(),
    drought_override_active: z.boolean().optional(),
    /** false = flat fallback carbon intensity, not real grid data */
    carbon_data_is_real: z.boolean().optional(),
    /** BC-02 [MR]: not in payloads today; accepted if the backend starts sending it. */
    physics_version: z.string().optional(),
  })
  .passthrough();
export type StateResponse = z.output<typeof StateResponse>;

export const SimulateResponse = z.array(StateResponse);
export type SimulateResponse = z.output<typeof SimulateResponse>;
