/**
 * FE-15: the `GET /api/scenarios` payload (BC-09, gate G-SCN).
 *
 * Contract rules kept here: nothing is defaulted, unknown extra fields are tolerated, and vocabulary fields stay the
 * raw string the backend sent (interpreted only in `model.ts`, so an unknown value remains unknown and never throws).
 * `id` is opaque: it is compared and echoed, never parsed.
 */
import { z } from 'zod';
import { num } from '@/contract/schemas/common';

const optText = z.string().nullable().optional();

export const ScenarioParameterSchema = z
  .object({
    name: z.string().min(1),
    type: z.string(),
    unit: optText,
    min: num.nullable().optional(),
    max: num.nullable().optional(),
    options: z.array(z.string()).nullable().optional(),
    default: z.union([num, z.string()]).nullable().optional(),
    description: optText,
  })
  .passthrough();

export const ScenarioDescriptorSchema = z
  .object({
    id: z.string().min(1),
    label: z.string().min(1),
    kind: optText,
    description: optText,
    weather_source: optText,
    plant: optText,
    control: optText,
    endpoint: optText,
    parameters: z.array(ScenarioParameterSchema).nullable().optional(),
  })
  .passthrough();

export const ScenarioRegistrySchema = z
  .object({
    registry_version: z.string(),
    scenarios: z.array(ScenarioDescriptorSchema),
  })
  .passthrough()
  .superRefine((registry, ctx) => {
    // Two scenarios with one id would make "selected by id" ambiguous: reject the payload, do not repair it.
    const seen = new Set<string>();
    registry.scenarios.forEach((s, i) => {
      if (seen.has(s.id)) ctx.addIssue({ code: 'custom', path: ['scenarios', i, 'id'], message: 'duplicate id' });
      seen.add(s.id);
    });
  });

export type ScenarioParameter = z.output<typeof ScenarioParameterSchema>;
export type ScenarioDescriptor = z.output<typeof ScenarioDescriptorSchema>;
export type ScenarioRegistry = z.output<typeof ScenarioRegistrySchema>;
