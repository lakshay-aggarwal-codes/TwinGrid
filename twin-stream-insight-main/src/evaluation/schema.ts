/**
 * FE-17 / BC-11 (gate G-EVAL): zod schemas for `GET /api/evaluations` and `GET /api/evaluations/{id}`.
 *
 * Shape source: docs/frontend/contracts/G-EVAL.md and its committed captures. The UI is a renderer of these payloads:
 *  - nothing is defaulted (a missing value stays missing and is shown as "not provided");
 *  - vocabulary strings (`outcome`, `claim_allowed`, `origin`, `kind`, `better`) stay strings and are interpreted in
 *    `model.ts`, where an unknown value is rendered neutrally;
 *  - `schema_version` other than 1 or 2 is a contract violation. 2 (amendment A2) adds the counted `pue_over_max_steps`
 *    hard constraint; a schema-1 report still loads and its PUE limit is shown as "not measured", never as zero.
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
    schema_version: z.union([z.literal(1), z.literal(2)]),
    generated_at_utc: z.string().nullish(),
    /** The physics label as registered (e.g. "legacy-0 (implicit)"). */
    physics_version: z.string().optional(),
    /** The physics the environment actually ran. Absent in reports written before the audit fix: shown as not reported. */
    physics_version_executed: z.string().optional(),
    scenario_inputs: z.string().optional(),
    carbon: z.object({ is_real: z.boolean().optional(), flat_curve: z.boolean().optional() }).passthrough().optional(),
    scenario_set_id: z.string().optional(),
    scenario_sets: z.record(z.object({ id: z.string(), n: finite }).passthrough()).optional(),
    preregistration_sha256: z.string().optional(),
    decision: DecisionSchema,
    policies: z.array(PolicySchema),
    /** Which envelope limits this report counted. A limit under `not_measured` was NOT counted (not the same as zero). */
    hard_constraints: z
      .object({ counted: z.array(z.string()), not_measured: z.array(z.string()), note: z.string().nullish() })
      .passthrough()
      .optional(),
    /** Only `best_constant_envelope_feasible` is read (comparator caveat); everything else stays untouched. */
    selection: z.object({ best_constant_envelope_feasible: z.boolean().optional() }).passthrough().optional(),
    metrics: z.record(MetricDefinitionSchema).optional(),
    outcome_definitions: z.record(z.string()).optional(),
    ci_level: finite.optional(),
  })
  .passthrough();
export type EvaluationResult = z.output<typeof EvaluationResultSchema>;
