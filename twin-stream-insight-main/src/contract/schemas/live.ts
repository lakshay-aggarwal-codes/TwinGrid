/** One /ws/live frame (BC-01): the state fields plus provenance/time fields and `anomaly_status`. */
import { z } from 'zod';
import { isoString, lenientEnum, num } from './common';
import { StateResponse } from './state';

export const AnomalyPipelineStatus = lenientEnum(['warming_up', 'ok', 'anomalous', 'unavailable', 'error'] as const);

/**
 * The backend's own error branch (live_broadcast_service._tick) emits only
 * `status, message, detector_id, trained_on`, so every other field is optional AND nullable.
 */
export const AnomalyStatusPayload = z
  .object({
    status: AnomalyPipelineStatus,
    message: z.string(),
    score: num.nullable().optional(),
    threshold: num.nullable().optional(),
    type: z.string().nullable().optional(),
    window_size: num.optional(),
    window_filled: num.optional(),
    seq: num.nullable().optional(),
    origin: lenientEnum(['measured', 'simulated', 'replayed'] as const).nullable().optional(),
    detector_id: z.string().optional(),
    model_version: z.string().nullable().optional(),
    trained_on: z.string().optional(),
    episode: z
      .object({
        open: z.boolean(),
        dedupe_key: z.string().nullable().optional(),
        alert_id: num.nullable().optional(),
        start_seq: num.nullable().optional(),
        severity: z.string().nullable().optional(),
      })
      .passthrough()
      .optional(),
    scored_at: z.string().optional(),
  })
  .passthrough();
export type AnomalyStatusPayload = z.output<typeof AnomalyStatusPayload>;

/** Provenance/time stamps are optional: an older backend does not send them (UI then shows "Unverified source"). */
export const LiveFrame = StateResponse.extend({
  schema_version: num.optional(),
  origin: lenientEnum(['measured', 'simulated', 'replayed'] as const).optional(),
  seq: num.optional(),
  ts_ingest: isoString.optional(), // aware UTC; interpret with parseInstant(..., 'ingest')
  sim_time: isoString.optional(), // simulated clock; never event time
  sim_time_scale: num.optional(),
  interval_s: num.optional(),
  anomaly_status: AnomalyStatusPayload.optional(),
}).passthrough();
export type LiveFrame = z.output<typeof LiveFrame>;
