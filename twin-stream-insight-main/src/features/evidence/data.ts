import claimsJson from "./generated/claims.json";
import limitationsJson from "./generated/limitations.json";
import ppoJson from "./generated/ppo_result.json";
import skillsJson from "./generated/skills.json";
import statusJson from "./generated/status.json";

/**
 * Task 26: the data behind /evidence. Everything here is generated from the repository's own documents by
 * `scripts/build_evidence.py` (run `python scripts/build_evidence.py --check` to see whether it is stale). Nothing is
 * fetched at run time, so the page works without the backend and for the read-only demo session.
 *
 * A value the generator could not find is the string "not recorded". The page shows it as such and never fills it in.
 */
export const NOT_RECORDED = "not recorded";

export type ClaimKind = "fact" | "result" | "assumption" | "hypothesis" | "future";
export interface Claim {
  id: string;
  text: string;
  kind: ClaimKind;
  evidence_paths: string[];
  limit: string;
}

export interface LimitationItem {
  title: string;
  text: string;
}
export interface LimitationSection {
  id: string;
  title: string;
  items: LimitationItem[];
}
export interface Limitations {
  source: string;
  model_status: { model: string; statement: string }[];
  sections: LimitationSection[];
}

export interface PpoRun {
  source_path: string;
  outcome: string;
  claim_allowed: string;
  reason: string;
  selected_seed: number | string;
  physics_version_executed: string;
  carbon_is_real: boolean | string;
  preregistration_sha256: string;
  scenario_set_id: string;
  n_test_scenarios: number | string;
  best_constant: string;
  generated_at_utc: string;
}
export interface PolicyRow {
  policy: string;
  total_reward: number | string;
  energy_kwh: number | string;
  water_L: number | string;
  mean_pue: number | string;
}
export interface PpoResult {
  outcome: string;
  claim_allowed: string;
  reason: string;
  runs: PpoRun[];
  policies: PolicyRow[];
  policies_source: string;
}

export type CheckResult = "pass" | "fail" | "skipped" | "not-run";
export interface StatusCheck {
  name: string;
  command?: string;
  result: CheckResult;
  counts?: string;
  log_path?: string;
}
export interface VerificationStatus {
  recorded: boolean;
  note?: string;
  recorded_at?: string;
  commit?: string;
  checks: StatusCheck[];
}

export interface SkillArea {
  id: string;
  title: string;
  files: { path: string; what: string }[];
}

export interface EvidenceData {
  claims: Claim[];
  limitations: Limitations;
  ppo: PpoResult;
  status: VerificationStatus;
  skills: SkillArea[];
}

export const GENERATED: EvidenceData = {
  claims: claimsJson as unknown as Claim[],
  limitations: limitationsJson as unknown as Limitations,
  ppo: ppoJson as unknown as PpoResult,
  status: statusJson as unknown as VerificationStatus,
  skills: skillsJson as unknown as SkillArea[],
};

/** Where the figures on the page come from (shown next to them). */
export const SOURCES = {
  claims: "docs/CLAIMS.md",
  limitations: "docs/model_cards/LIMITATIONS.md",
  status: "evidence/status.json",
  architecture: "docs/architecture/system.md",
} as const;

// ---- claims ledger -----------------------------------------------------------------------------------------------

export type ClaimGroup = "supported" | "assumption" | "not-supported";
export type ClaimFilter = "all" | ClaimGroup;

/** fact and result are backed by a file or a run (within the stated limit); the rest are not. Unknown kinds count as not supported. */
export function claimGroup(kind: string): ClaimGroup {
  if (kind === "fact" || kind === "result") return "supported";
  if (kind === "assumption") return "assumption";
  return "not-supported";
}

export const CLAIM_FILTERS: readonly { id: ClaimFilter; label: string; hint: string }[] = [
  { id: "all", label: "All", hint: "every row of the ledger" },
  { id: "supported", label: "Supported", hint: "fact or result, within the limit shown" },
  { id: "assumption", label: "Assumption", hint: "something the simulator takes as given" },
  { id: "not-supported", label: "Not supported", hint: "hypothesis or not built" },
];

export function filterClaims(claims: readonly Claim[], filter: ClaimFilter): Claim[] {
  return filter === "all" ? [...claims] : claims.filter((c) => claimGroup(c.kind) === filter);
}

export function countClaims(claims: readonly Claim[], filter: ClaimFilter): number {
  return filterClaims(claims, filter).length;
}

// ---- model status ------------------------------------------------------------------------------------------------

/** Ledger rows that carry a model's reported figure next to its limit. Looked up by id; absent ids are skipped. */
export const MODEL_CLAIM_IDS: readonly string[] = ["C-06", "C-07"];

export function claimById(claims: readonly Claim[], id: string): Claim | undefined {
  return claims.find((c) => c.id === id);
}

/** The policy with the highest mean reward in the table, or null when no policy has a numeric reward. Display only; it decides nothing. */
export function highestReward(policies: readonly PolicyRow[]): PolicyRow | null {
  let best: PolicyRow | null = null;
  for (const p of policies) {
    if (typeof p.total_reward !== "number") continue;
    if (best === null || p.total_reward > (best.total_reward as number)) best = p;
  }
  return best;
}

/** A number to `digits` places, a string (including "not recorded") as it is. */
export function fmt(v: unknown, digits = 2): string {
  if (typeof v === "number" && Number.isFinite(v)) return v.toFixed(digits);
  if (typeof v === "string" && v !== "") return v;
  return NOT_RECORDED;
}

// ---- architecture ------------------------------------------------------------------------------------------------

/** What each box is, in words. Also rendered as a list so the diagram has a text equivalent. */
export const BOUNDARIES: readonly { name: string; detail: string }[] = [
  { name: "Browser", detail: "React, Vite and Three.js (twin-stream-insight-main). Talks to the API over REST and one WebSocket (/ws/live)." },
  { name: "FastAPI backend", detail: "api/: middleware (request id, CORS, body limit), routes, plugins, services, repositories, and a supervisor that runs the live broadcast loop." },
  { name: "Simulator and models", detail: "src/: the physics simulator, the reinforcement-learning environment built on it, the anomaly detector and forecaster. Models are loaded through an artifact gate that reads models/registry.json." },
  { name: "Storage", detail: "Postgres (SQLAlchemy and Alembic), Redis for the job queue, and model files under models/." },
  { name: "Worker", detail: "An RQ worker runs queued jobs against the same simulator." },
  { name: "Real facility", detail: "Not connected. There is no BACnet, Modbus or SNMP integration, and nothing here controls equipment." },
];
