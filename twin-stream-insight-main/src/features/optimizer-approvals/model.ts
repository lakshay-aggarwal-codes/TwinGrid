/**
 * Task 19: data model and pure helpers for the optimizer page (no React, no network).
 *
 * What the page may and may not say (see `claimGate`): PPO is never described as better than the baselines unless the
 * STORED evaluation decision (from `GET /api/models/passport`) has outcome "A", and then only the stored `claim_allowed`
 * text is shown, verbatim. Predicted effects are twin simulations ("model estimate on simulated data"). An approval is a
 * recorded decision; nothing is applied to equipment.
 */
import { z } from "zod";
import { roleAllows } from "../roles";
import type { Passport } from "../explainability/model";

export const MODES = ["free_air", "closed_loop", "evaporative", "hybrid"] as const;
export type Mode = (typeof MODES)[number];
export const CHILLED_MIN_C = 5;
export const CHILLED_MAX_C = 15;
export const MAX_NOTE_CHARS = 500;

export const MODE_LABEL: Readonly<Record<string, string>> = {
  free_air: "Free air",
  closed_loop: "Closed loop",
  evaporative: "Evaporative",
  hybrid: "Hybrid",
};
export const modeLabel = (mode: string): string => MODE_LABEL[mode] ?? mode;

export const PREDICTION_LABEL = "model estimate on simulated data";
export const APPROVAL_NOTE = "A decision is recorded only. TwinGrid does not apply setpoints to any equipment.";

// ------------------------------------------------------------------------------------------------ schemas

const Metrics = z.object({
  mean_pue: z.number(),
  total_energy_kwh: z.number(),
  total_co2_kg: z.number(),
  max_outlet_temp_C: z.number(),
  thermal_margin_C: z.number(),
});
export type MetricKey = keyof z.output<typeof Metrics>;

export const EffectSchema = z
  .object({
    label: z.string(),
    hours: z.number().nullable().optional(),
    reference: Metrics,
    proposed: Metrics,
    delta: Metrics,
    outlet_limit_C: z.number(),
    within_outlet_limit: z.boolean(),
    carbon_data_is_real: z.boolean(),
  })
  .passthrough();
export type Effect = z.output<typeof EffectSchema>;

const SelectedSchema = z
  .object({
    name: z.string(),
    validation_reward: z.number(),
    tuner_version: z.string(),
    config: z.string(),
    chilled_water_temp_C: z.number(),
    cooling_mode: z.string(),
    basis: z.string(),
  })
  .passthrough();

export const RecommendationSchema = z
  .object({
    recommendation: z.object({
      selected: SelectedSchema.nullable(),
      considered: z.array(
        z.object({
          name: z.string(),
          usable: z.boolean(),
          reason: z.string().nullable(),
          validation_reward: z.number().nullable(),
          status: z.string().nullable(),
        }),
      ),
      note: z.string(),
    }),
    predicted: EffectSchema.nullable(),
    persisted: z.literal(false),
  })
  .passthrough();
export type Recommendation = z.output<typeof RecommendationSchema>;

export const SandboxSchema = z.object({ predicted: EffectSchema, persisted: z.literal(false) }).passthrough();
export type Sandbox = z.output<typeof SandboxSchema>;

export const PROPOSAL_STATUSES = ["pending", "approved", "rejected"] as const;
export type ProposalStatus = (typeof PROPOSAL_STATUSES)[number];

export const ProposalSchema = z
  .object({
    id: z.number(),
    created_at: z.string().nullable(),
    proposer: z.string(),
    source: z.string(),
    chilled_water_temp_C: z.number(),
    cooling_mode: z.string(),
    predicted: EffectSchema,
    rationale: z.string().nullable(),
    origin: z.string(),
    status: z.enum(PROPOSAL_STATUSES),
    decided_by: z.string().nullable(),
    decided_at: z.string().nullable(),
    decision_note: z.string().nullable(),
    approval_label: z.string(),
  })
  .passthrough();
export type Proposal = z.output<typeof ProposalSchema>;
export const ProposalListSchema = z.array(ProposalSchema);

export const ShadowSchema = z
  .object({
    n_samples: z.number(),
    agreement_rate: z.number().nullable(),
    message: z.string().optional(),
    period: z.object({ from: z.string(), to: z.string() }).optional(),
  })
  .passthrough();
export type ShadowSummary = z.output<typeof ShadowSchema>;

// ------------------------------------------------------------------------------------------------ requests

/** The conditions a prediction is made for, and the current settings it is compared with. */
export interface Context {
  utilisation: number;
  outside_temp: number;
  water_stress: number;
  /** The CURRENT cooling mode ("auto" or a mode) and chilled-water set-point. */
  mode: string;
  chilled_water_temp: number;
  /** A measured inlet temperature from the live feed, or null. Only used by the PID baseline. */
  inlet_temp_c: number | null;
}

export interface Setpoints {
  chilled_water_temp_c: number;
  cooling_mode: Mode;
}

function contextQuery(ctx: Context): Record<string, string> {
  const q: Record<string, string> = {
    utilisation: String(ctx.utilisation),
    outside_temp: String(ctx.outside_temp),
    water_stress: String(ctx.water_stress),
    current_mode: ctx.mode,
    current_chilled_water_temp: String(ctx.chilled_water_temp),
  };
  if (ctx.inlet_temp_c !== null) q.inlet_temp_c = String(ctx.inlet_temp_c);
  return q;
}
export const recommendationQuery = contextQuery;
export const sandboxQuery = (ctx: Context, sp: Setpoints): Record<string, string> => ({
  ...contextQuery(ctx),
  proposed_chilled_water_temp: String(sp.chilled_water_temp_c),
  proposed_mode: sp.cooling_mode,
});

export interface ProposalBody {
  utilisation: number;
  outside_temp: number;
  water_stress: number;
  current_mode: string;
  current_chilled_water_temp: number;
  inlet_temp_c?: number;
  chilled_water_temp_c: number;
  cooling_mode: Mode;
  rationale?: string;
}
export function proposalBody(ctx: Context, sp: Setpoints, rationale: string): ProposalBody {
  const body: ProposalBody = {
    utilisation: ctx.utilisation,
    outside_temp: ctx.outside_temp,
    water_stress: ctx.water_stress,
    current_mode: ctx.mode,
    current_chilled_water_temp: ctx.chilled_water_temp,
    chilled_water_temp_c: sp.chilled_water_temp_c,
    cooling_mode: sp.cooling_mode,
  };
  if (ctx.inlet_temp_c !== null) body.inlet_temp_c = ctx.inlet_temp_c;
  const text = rationale.trim();
  if (text) body.rationale = text;
  return body;
}

/** The legacy registry bounds: what the form allows when the backend says nothing about the physics' range. */
export const LEGACY_CHILLED_RANGE: readonly [number, number] = [CHILLED_MIN_C, CHILLED_MAX_C];

export const RECOMMENDATION_EVIDENCE_NOTE =
  "The stored validation reward is a simulated score on validation scenarios: not a test-set result and not measured on a real facility.";

/** `effect.setpoint_check` (additive backend payload), read defensively. Null when absent or malformed. */
export interface SetpointCheck {
  readonly physics: string | null;
  readonly actuatorRange: readonly [number, number] | null;
  readonly proposedWithin: boolean | null;
  readonly referenceWithin: boolean | null;
}

export function setpointCheckOf(effect: object | null | undefined): SetpointCheck | null {
  const raw = effect === null || effect === undefined ? undefined : (effect as Record<string, unknown>).setpoint_check;
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const r = raw as Record<string, unknown>;
  const range = r.actuator_range_C;
  const ok = Array.isArray(range) && range.length === 2 && range.every((x) => typeof x === "number" && Number.isFinite(x));
  const bool = (v: unknown) => (typeof v === "boolean" ? v : null);
  return {
    physics: typeof r.physics_version === "string" && r.physics_version !== "" ? r.physics_version : null,
    actuatorRange: ok ? ([range[0], range[1]] as [number, number]) : null,
    proposedWithin: bool(r.proposed_within_actuator_range),
    referenceWithin: bool(r.reference_within_actuator_range),
  };
}

/**
 * The chilled-water inputs the form accepts: the union of the legacy bounds and the evaluated actuator range, which
 * mirrors the server (`accepted_chilled_range_C`). The range is physics-dependent (legacy-0 5..15 C, physics 1
 * 16..25 C), so a fixed 5..15 would reject the baseline's own physics-1 recommendation. The server still decides.
 */
export function acceptedChilledRange(check: SetpointCheck | null): readonly [number, number] {
  if (check === null || check.actuatorRange === null) return LEGACY_CHILLED_RANGE;
  return [Math.min(CHILLED_MIN_C, check.actuatorRange[0]), Math.max(CHILLED_MAX_C, check.actuatorRange[1])];
}

/** Notices about the evaluated range, as words (never colour alone). Empty when the backend sent no check. */
export function setpointNotices(check: SetpointCheck | null): string[] {
  if (check === null || check.actuatorRange === null) return [];
  const [lo, hi] = check.actuatorRange;
  const where = `${lo}–${hi} °C range the evaluated controllers could command${check.physics ? ` under physics ${check.physics}` : ""}`;
  const out: string[] = [];
  if (check.proposedWithin === false) out.push(`The proposed set-point is outside the ${where}. No baseline was evaluated there, and it can leave the inlet safety band.`);
  if (check.referenceWithin === false) out.push(`Your current set-point is outside the ${where}.`);
  return out;
}

/** Why these set-points cannot be sent, or null when they can. (The server checks again.) */
export function setpointProblem(
  sp: { chilled_water_temp_c: number; cooling_mode: string },
  range: readonly [number, number] = LEGACY_CHILLED_RANGE,
): string | null {
  if (!Number.isFinite(sp.chilled_water_temp_c)) return "Enter a chilled-water temperature.";
  if (sp.chilled_water_temp_c < range[0] || sp.chilled_water_temp_c > range[1]) {
    return `The chilled-water set-point must be between ${range[0]} and ${range[1]} °C.`;
  }
  if (!(MODES as readonly string[]).includes(sp.cooling_mode)) return "Choose a cooling mode.";
  return null;
}

// ------------------------------------------------------------------------------------------------ effect table

const ROWS: readonly { key: MetricKey; label: string; unit: string; digits: number }[] = [
  { key: "mean_pue", label: "Mean PUE", unit: "", digits: 3 },
  { key: "total_energy_kwh", label: "Energy (24 h)", unit: "kWh", digits: 0 },
  { key: "total_co2_kg", label: "Carbon (24 h)", unit: "kg CO₂", digits: 1 },
  { key: "max_outlet_temp_C", label: "Hottest outlet", unit: "°C", digits: 1 },
  { key: "thermal_margin_C", label: "Thermal margin", unit: "°C", digits: 1 },
];

export interface EffectRow {
  key: MetricKey;
  label: string;
  unit: string;
  reference: string;
  proposed: string;
  delta: string;
  /** Words, not colour: "lower", "higher" or "unchanged". */
  direction: "lower" | "higher" | "unchanged";
}

export function formatNumber(value: number, digits: number): string {
  return value.toFixed(digits);
}

export function signed(value: number, digits: number): string {
  const text = Math.abs(value).toFixed(digits);
  if (Number(text) === 0) return `${text}`;
  return `${value > 0 ? "+" : "−"}${text}`;
}

export function effectRows(effect: Effect): EffectRow[] {
  return ROWS.map((r) => {
    const d = Number(Math.abs(effect.delta[r.key]).toFixed(r.digits));
    return {
      key: r.key,
      label: r.label,
      unit: r.unit,
      reference: formatNumber(effect.reference[r.key], r.digits),
      proposed: formatNumber(effect.proposed[r.key], r.digits),
      delta: signed(effect.delta[r.key], r.digits),
      direction: d === 0 ? "unchanged" : effect.delta[r.key] > 0 ? "higher" : "lower",
    };
  });
}

// ------------------------------------------------------------------------------------------------ PPO state and claim gate

export interface ClaimGate {
  /** The stored decision's outcome letter or state, e.g. "A" or "NOT_EVALUATED". */
  outcome: string;
  allowed: boolean;
  /** The stored `claim_allowed` text, verbatim, and ONLY when the outcome is "A". */
  claimText: string | null;
  reason: string | null;
  evaluationId: string | null;
}

/**
 * May the page say anything about PPO against the baselines? Only if the stored decision is outcome "A" with a
 * non-empty claim; then the stored text is the whole claim. Anything else (no report, NOT_EVALUATED, B, C, a missing
 * decision) allows no claim at all.
 */
export function claimGate(passport: Passport | null | undefined): ClaimGate {
  const ppo = passport?.models.find((m) => m.kind === "ppo" && m.evaluation !== null);
  const ev = ppo?.evaluation ?? null;
  if (!ev) return { outcome: "NOT_EVALUATED", allowed: false, claimText: null, reason: null, evaluationId: null };
  const text = ev.claim_allowed.trim();
  const allowed = ev.outcome === "A" && text !== "" && text.toLowerCase() !== "none";
  return {
    outcome: ev.outcome,
    allowed,
    claimText: allowed ? ev.claim_allowed : null,
    reason: ev.reason ?? null,
    evaluationId: ev.evaluation_id ?? null,
  };
}

export interface PpoAvailability {
  /** The registry holds at least one promoted PPO policy the API may load. This is not proof the gate will admit it. */
  registryHasPromoted: boolean;
  /** The newest PPO entry's status line, or null when the registry lists none. */
  statusText: string | null;
}
export function ppoAvailability(passport: Passport | null | undefined): PpoAvailability {
  const entries = passport?.models.filter((m) => m.kind === "ppo") ?? [];
  const newest = entries.length > 0 ? entries[entries.length - 1] : null;
  return {
    registryHasPromoted: entries.some((m) => m.loadable),
    statusText: newest ? (newest.status_reason ? `${newest.status}: ${newest.status_reason}` : newest.status) : null,
  };
}

// ------------------------------------------------------------------------------------------------ roles

/** UX gates only; the backend decides. Operators and admins may propose; only admins may decide. */
export const canPropose = (role: string | null | undefined): boolean => roleAllows(role, "operator");
export const canDecide = (role: string | null | undefined): boolean => roleAllows(role, "admin");

/** An admin may decide a pending proposal that somebody else made. */
export function decisionBlock(role: string | null | undefined, username: string | null | undefined, p: Proposal): string | null {
  if (!canDecide(role)) return "Only an admin can approve or reject.";
  if (p.status !== "pending") return "Already decided.";
  if (username && p.proposer === username) return "You made this proposal, so someone else must decide it.";
  return null;
}

// ------------------------------------------------------------------------------------------------ shadow mode

export interface ShadowBars {
  total: number;
  agree: number;
  differ: number;
  /** Percent, one decimal, or null when nothing was sampled. */
  ratePct: string | null;
}
export function shadowBars(s: ShadowSummary): ShadowBars {
  if (s.n_samples <= 0 || s.agreement_rate === null) return { total: 0, agree: 0, differ: 0, ratePct: null };
  const agree = Math.round(s.agreement_rate * s.n_samples);
  return { total: s.n_samples, agree, differ: s.n_samples - agree, ratePct: (s.agreement_rate * 100).toFixed(1) };
}
