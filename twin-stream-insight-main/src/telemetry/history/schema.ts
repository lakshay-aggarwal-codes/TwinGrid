/**
 * FE-18 / BC-12 (gate G-HIST): zod schemas for the telemetry read API.
 *
 *   GET /api/telemetry/sensors/{external_id}/samples   GET /api/telemetry/sensors/{external_id}/gaps   GET /api/facility
 *
 * Shape source: docs/frontend/contracts/G-HIST.md and its committed captures (synthetic test values: shape and
 * vocabulary only). Vocabulary strings (`origin`, `quality`, `invalid_reason`, `stream`) stay strings and are
 * interpreted in `model.ts` / `origin.ts`; an unknown value is shown as unknown. `value` is never null on this API:
 * a missing point is an absence. Nothing is defaulted.
 */
import { z } from 'zod';

const finite = z.number().finite();

export const TelemetrySampleSchema = z
  .object({
    ts_event: z.string().min(1),
    ts_ingest: z.string().nullish(),
    value: finite,
    origin: z.string().nullish(),
    stream_id: z.string().nullish(),
    quality: z.string().nullish(),
    invalid_reason: z.string().nullish(),
  })
  .passthrough();
export type TelemetrySample = z.output<typeof TelemetrySampleSchema>;

export const TelemetrySamplesSchema = z
  .object({
    external_id: z.string().min(1),
    unit: z.string().nullish(),
    sampling_interval_s: finite.positive().nullish(),
    stream: z.string(),
    quality: z.string(),
    items: z.array(TelemetrySampleSchema),
    next_cursor: z.string().min(1).nullable(),
  })
  .passthrough();
export type TelemetrySamplesPage = z.output<typeof TelemetrySamplesSchema>;

export const TelemetryGapSchema = z.object({ start: z.string().min(1), end: z.string().min(1), duration_s: finite }).passthrough();
export type TelemetryGap = z.output<typeof TelemetryGapSchema>;

export const TelemetryGapsSchema = z
  .object({
    external_id: z.string().min(1),
    stream: z.string(),
    sampling_interval_s: finite.positive().nullish(),
    threshold_s: finite.nullish(),
    gaps: z.array(TelemetryGapSchema),
    truncated: z.boolean(),
  })
  .passthrough();
export type TelemetryGaps = z.output<typeof TelemetryGapsSchema>;

/** Only the facility id is used (to build `fac<id>.<measurand>`); the rest of the record is ignored. */
export const FacilityIdSchema = z.object({ id: z.number().int().positive() }).passthrough();
export type FacilityId = z.output<typeof FacilityIdSchema>;
