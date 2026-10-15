import type { Passport } from "../explainability/model";
import type { Effect, Proposal, Recommendation } from "./model";

/** SYNTHETIC values for tests (the shapes of the /api/optimizer/* responses). */
export const EFFECT: Effect = {
  label: "model estimate on simulated data",
  hours: 24,
  reference: { mean_pue: 1.5, total_energy_kwh: 1000, total_co2_kg: 400, max_outlet_temp_C: 30, thermal_margin_C: 5 },
  proposed: { mean_pue: 1.4, total_energy_kwh: 900, total_co2_kg: 360, max_outlet_temp_C: 33, thermal_margin_C: 2 },
  delta: { mean_pue: -0.1, total_energy_kwh: -100, total_co2_kg: -40, max_outlet_temp_C: 3, thermal_margin_C: -3 },
  outlet_limit_C: 35,
  within_outlet_limit: true,
  carbon_data_is_real: false,
};

export const RECOMMENDATION: Recommendation = {
  recommendation: {
    selected: {
      name: "pid",
      validation_reward: -91.05,
      tuner_version: "1",
      config: "configs/baselines/pid.json",
      chilled_water_temp_C: 12,
      cooling_mode: "hybrid",
      basis: "the PID nominal set-point (no inlet temperature was supplied) and the production cooling-mode rule",
    },
    considered: [
      { name: "pid", usable: true, reason: null, validation_reward: -91.05, status: "feasible" },
      { name: "rule", usable: false, reason: "tuned against different code or scenarios than the running ones; re-tune it", validation_reward: -92.16, status: "feasible" },
    ],
    note: "Ranked by the validation reward stored in each baseline's config (higher is better), measured on simulated validation scenarios. It is not an evaluation on this facility and not a comparison with PPO.",
  },
  predicted: EFFECT,
  persisted: false,
};

export function proposal(over: Partial<Proposal> = {}): Proposal {
  return {
    id: 1,
    created_at: "2026-10-01T08:00:00+00:00",
    proposer: "operator1",
    source: "baseline:pid",
    chilled_water_temp_C: 12,
    cooling_mode: "hybrid",
    predicted: EFFECT,
    rationale: null,
    origin: "simulated",
    status: "pending",
    decided_by: null,
    decided_at: null,
    decision_note: null,
    approval_label: "A decision is recorded only. TwinGrid does not apply setpoints to any equipment.",
    ...over,
  };
}

export function passport(opts: { outcome?: string; claim?: string; loadable?: boolean; noEvaluation?: boolean } = {}): Passport {
  const evaluation = opts.noEvaluation
    ? null
    : { outcome: opts.outcome ?? "NOT_EVALUATED", claim_allowed: opts.claim ?? "none", reason: "stored reason text", source: "reports/x.json", evaluation_id: "ev-1" };
  return {
    models: [{ kind: "ppo", status: "quarantined", status_reason: "no promoted policy", loadable: opts.loadable ?? false, evaluation }],
  } as unknown as Passport;
}
