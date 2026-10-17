/**
 * FE-16: run record and run result (BC-10, gate G-RUN). Nothing is defaulted; unknown extra fields are tolerated;
 * `status` and `failure_code` stay the raw string the backend sent (interpreted only in `model.ts`, so an unknown
 * value stays unknown and never throws). Output numbers must be numbers: a string is rejected, not coerced.
 */
import { z } from 'zod';
import { isoString, num } from '@/contract/schemas/common';

const paramValue = z.union([num, z.string()]);
const optText = z.string().nullable().optional();
const optNum = num.nullable().optional();

export const RunRecordSchema = z
  .object({
    run_id: z.string().min(1),
    kind: optText,
    status: z.string(),
    scenario_id: z.string().min(1),
    scenario_set_id: optText,
    registry_version: optText,
    parameters: z.record(paramValue).nullable().optional(),
    created_at: isoString,
    started_at: isoString.nullable().optional(),
    ended_at: isoString.nullable().optional(),
    failure_code: optText,
    result_url: optText,
  })
  .passthrough();

export const RunProvenanceSchema = z
  .object({
    origin: optText,
    scenario_kind: optText,
    weather_source: optText,
    plant: optText,
    control: optText,
    physics_version: optText,
    model_version: optText,
    carbon_data_is_real: z.boolean().nullable().optional(),
  })
  .passthrough();

export const RunOutputsSchema = z
  .object({
    hours: optNum,
    basis: optText,
    mean_pue: optNum,
    wue: optNum,
    total_water_L: optNum,
    total_energy_kwh: optNum,
    total_co2_kg: optNum,
    max_outlet_temp_C: optNum,
    final_cooling_mode: optText,
    drought_override_active: z.boolean().nullable().optional(),
    carbon_data_is_real: z.boolean().nullable().optional(),
  })
  .passthrough();

export const RunResultSchema = z
  .object({
    run_id: z.string().min(1),
    kind: optText,
    scenario_id: z.string().min(1),
    scenario_set_id: optText,
    registry_version: optText,
    parameters: z.record(paramValue).nullable().optional(),
    started_at: isoString.nullable().optional(),
    ended_at: isoString.nullable().optional(),
    provenance: RunProvenanceSchema.nullable().optional(),
    outputs: RunOutputsSchema.nullable().optional(),
  })
  .passthrough();

export type RunRecord = z.output<typeof RunRecordSchema>;
export type RunResult = z.output<typeof RunResultSchema>;
