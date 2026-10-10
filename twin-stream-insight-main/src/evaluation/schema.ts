/**
 * FE-17 / BC-11 (gate G-EVAL): zod schemas for `GET /api/evaluations` and `GET /api/evaluations/{id}`.
 *
 * Shape source: docs/frontend/contracts/G-EVAL.md and its committed captures. The UI is a renderer of these payloads:
 *  - nothing is defaulted (a missing value stays missing and is shown as "not provided");
 *  - vocabulary strings (`outcome`, `claim_allowed`, `origin`, `kind`, `better`) stay strings and are interpreted in
 *    `model.ts`, where an unknown value is rendered neutrally;
 *  - `schema_version` other than 1 is a contract violation (the endpoint serves the v1 format only).
 */
import { z } from 'zod';

const finite = z.number().finite();

export const EvaluationSummarySchema = z
  .object({
    evaluation_id: z.string().min(1),
    source: z.string(),
    generated_at_utc: z.string().nullish(),
    outcome: z.string().nullish(),
    claim_allowed: z.string().nullish(),
    ppo_evaluated: z.boolean(),
  })
  .passthrough();
export type EvaluationSummary = z.output<typeof EvaluationSummarySchema>;

export const EvaluationListSchema = z.object({ evaluations: z.array(EvaluationSummarySchema) }).passthrough();
export type EvaluationList = z.output<typeof EvaluationListSchema>;

const DecisionSchema = z
  .object({
    outcome: z.string().min(1),
    claim_allowed: z.string(),
    reason: z.string().optional(),
    /** Present only when PPO candidates were evaluated. Read defensively in `model.ts`; never trusted blindly. */
    detail: z.unknown().optional(),
  })
  .passthrough();
export type EvaluationDecision = z.output<typeof DecisionSchema>;

const PolicySchema = z
  .object({
    policy_id: z.string().min(1),
    kind: z.string().optional(),
    metrics: z.record(finite),
  })
  .passthrough();
export type EvaluationPolicy = z.output<typeof PolicySchema>;

const MetricDefinitionSchema = z.object({ better: z.string().optional(), definition: z.string().optional() }).passthrough();
export type MetricDefinition = z.output<typeof MetricDefinitionSchema>;

export const EvaluationResultSchema = z
  .object({
    evaluation_id: z.string().min(1),
    source: z.string(),
    origin: z.string().optional(),
    schema_version: z.literal(1),
    generated_at_utc: z.string().nullish(),
    physics_version: z.string().optional(),
    scenario_inputs: z.string().optional(),
    carbon: z.object({ is_real: z.boolean().optional(), flat_curve: z.boolean().optional() }).passthrough().optional(),
    scenario_set_id: z.string().optional(),
    scenario_sets: z.record(z.object({ id: z.string(), n: finite }).passthrough()).optional(),
    preregistration_sha256: z.string().optional(),
    decision: DecisionSchema,
    policies: z.array(PolicySchema),
    metrics: z.record(MetricDefinitionSchema).optional(),
    outcome_definitions: z.record(z.string()).optional(),
    ci_level: finite.optional(),
  })
  .passthrough();
export type EvaluationResult = z.output<typeof EvaluationResultSchema>;
