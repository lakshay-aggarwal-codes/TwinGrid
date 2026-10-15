/**
 * Task 18: data model and pure helpers for explanations and the Model Passport (no React, no network).
 *
 * Everything shown comes from `GET /api/models/passport`, `GET /api/alerts/{id}/explanation` or the live frame's
 * `anomaly_status.explanation`. Nothing here estimates a number: sentences only restate numbers the backend sent.
 */
import { z } from "zod";
import { unitFor } from "@/contract/units";

export const SYNTHETIC_LABEL = "synthetic-data result";

const nstr = z.string().nullable().optional();

export const PassportModelSchema = z
  .object({
    model_id: z.string(),
    name: nstr,
    kind: z.string(),
    version: nstr,
    status: z.string(),
    status_reason: nstr,
    loadable: z.boolean(),
    created_at_utc: nstr,
    data_origin: z.string(),
    data_origin_basis: nstr,
    data_source: nstr,
    dataset_id: nstr,
    physics_version: nstr,
    metrics_label: z.string(),
    headline_metrics: z.array(z.object({ name: z.string(), value: z.number() })),
    limitations: z.array(z.string()),
    limitations_source: z.array(z.string()),
    claim_boundary: z.string(),
    evaluation: z
      .object({
        outcome: z.string(),
        claim_allowed: z.string(),
        reason: nstr,
        source: z.string(),
        evaluation_id: nstr,
      })
      .nullable(),
    explanation_method: nstr,
    detector: z
      .object({ threshold: z.number(), threshold_percentile: z.number().nullable().optional(), feature_columns: z.array(z.string()) })
      .nullable()
      .optional(),
  })
  .passthrough();
export type PassportModel = z.output<typeof PassportModelSchema>;

export const PassportSchema = z
  .object({
    schema_version: z.literal(1),
    origin: z.string(),
    metrics_label: z.string(),
    sources: z.array(z.string()),
    models: z.array(PassportModelSchema),
  })
  .passthrough();
export type Passport = z.output<typeof PassportSchema>;

const FeatureSchema = z.object({
  feature: z.string(),
  value: z.number(),
  train_min: z.number(),
  train_max: z.number(),
  position: z.number(),
  centre_distance: z.number(),
  outside_range_by: z.number(),
  outside_range: z.boolean(),
  rank: z.number(),
});
export type FeatureDeviation = z.output<typeof FeatureSchema>;

export const ExplanationSchema = z
  .object({
    alert_id: z.number(),
    model_version: nstr,
    method: z.string(),
    method_text: z.string(),
    threshold_basis: z.string(),
    score_vs_threshold: z
      .object({
        score: z.number(),
        threshold: z.number(),
        ratio: z.number(),
        margin: z.number(),
        over_threshold: z.boolean(),
        critical_above: z.number(),
        severity_by_rule: z.string(),
      })
      .nullable(),
    features: z.array(FeatureSchema).nullable(),
    unavailable: z.array(z.string()),
    reading_origin: nstr,
  })
  .passthrough();
export type Explanation = z.output<typeof ExplanationSchema>;

// ---------------------------------------------------------------------------------------------- wording

export const KIND_LABEL: Readonly<Record<string, string>> = {
  anomaly: "Anomaly detector",
  forecaster: "Thermal forecaster",
  ppo: "Cooling optimizer (PPO)",
};
export const kindLabel = (kind: string): string => KIND_LABEL[kind] ?? `Model of kind "${kind}"`;

export type StatusIcon = "promoted" | "candidate" | "quarantined" | "rejected" | "retired" | "unknown";
const STATUS_TEXT: Readonly<Record<string, { icon: StatusIcon; text: string }>> = {
  promoted: { icon: "promoted", text: "Promoted: the API may load it" },
  candidate: { icon: "candidate", text: "Candidate: not promoted, the API does not load it" },
  quarantined: { icon: "quarantined", text: "Quarantined: the API does not load it" },
  rejected: { icon: "rejected", text: "Rejected: the API does not load it" },
  retired: { icon: "retired", text: "Retired: the API does not load it" },
};
export function statusView(status: string): { icon: StatusIcon; text: string } {
  return STATUS_TEXT[status] ?? { icon: "unknown", text: `Status "${status}" (not recognised by this page)` };
}

const METRIC_LABEL: Readonly<Record<string, string>> = {
  f1: "F1",
  precision: "Precision",
  recall: "Recall",
  rmse: "RMSE",
  mae: "MAE",
  pue_improvement_mean_pct: "PUE improvement, mean over seeds (%)",
  pue_improvement_std_pct: "PUE improvement, std over seeds (%)",
  pue_improvement_ci95_pct: "PUE improvement, 95% CI half-width (%)",
};
export const metricLabel = (name: string): string => METRIC_LABEL[name] ?? name;
/** Four significant digits; the exact registry number is kept in the cell's title. */
export const formatMetric = (v: number): string => (Number.isFinite(v) ? Number(v.toPrecision(4)).toString() : "not a number");

export function modelsFor(passport: Passport, kind: string | null): PassportModel[] {
  return kind === null ? [...passport.models] : passport.models.filter((m) => m.kind === kind);
}

const featureLabel = (name: string): string => {
  const u = unitFor(name);
  return u ? `${u.label}${u.unit ? ` (${u.unit})` : ""}` : name;
};
export { featureLabel };

const num = (v: number, d = 3) => v.toFixed(d);
const pct = (v: number) => `${Math.round(v * 100)}%`;

/** "Score 0.0300 is 3.00x the alert threshold 0.0100; the alert rule fires above the threshold and CRITICAL above 0.0200." */
export function scoreSentence(s: NonNullable<Explanation["score_vs_threshold"]>): string {
  const rel = s.over_threshold ? "above" : "not above";
  return `Score ${num(s.score, 4)} is ${s.ratio.toFixed(2)}x the alert threshold ${num(s.threshold, 4)} (${rel} it). The alert rule fires above the threshold; the severity rule says CRITICAL above ${num(s.critical_above, 4)}.`;
}

/** One sentence per signal, restating the backend's numbers. */
export function deviationSentence(f: FeatureDeviation): string {
  const range = `${num(f.train_min, 1)} to ${num(f.train_max, 1)}`;
  if (f.outside_range) {
    const side = f.position > 1 ? "above the top" : "below the bottom";
    return `${featureLabel(f.feature)} is ${num(f.value, 1)}: ${pct(f.outside_range_by)} of the range width ${side} of the training range (${range}).`;
  }
  return `${featureLabel(f.feature)} is ${num(f.value, 1)}: ${pct(f.position)} of the way through the training range (${range}).`;
}

export interface LiveShare {
  readonly feature: string;
  readonly pct: number;
}
export interface LiveWhy {
  readonly shares: readonly LiveShare[];
  readonly top: string | null;
  readonly totalError: number | null;
}

/**
 * The detector's own reconstruction-error shares from `anomaly_status.explanation` (live frame). Defensive: anything that
 * is not a map of finite non-negative numbers is "no explanation", never a partial one.
 */
export function liveWhy(explanation: unknown): LiveWhy | null {
  if (typeof explanation !== "object" || explanation === null) return null;
  const raw = (explanation as { feature_contributions_pct?: unknown }).feature_contributions_pct;
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const entries = Object.entries(raw as Record<string, unknown>);
  if (entries.length === 0 || !entries.every(([, v]) => typeof v === "number" && Number.isFinite(v) && v >= 0)) return null;
  const shares = entries.map(([feature, v]) => ({ feature, pct: v as number })).sort((a, b) => b.pct - a.pct || a.feature.localeCompare(b.feature));
  const top = (explanation as { top_feature?: unknown }).top_feature;
  const total = (explanation as { total_error?: unknown }).total_error;
  return { shares, top: typeof top === "string" ? top : shares[0].feature, totalError: typeof total === "number" && Number.isFinite(total) ? total : null };
}
