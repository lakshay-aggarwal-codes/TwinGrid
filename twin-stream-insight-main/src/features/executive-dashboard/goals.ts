import { OUTLET_SCALE } from "@/three/thermalMapping";

/**
 * Task 16: goal-ring targets. Every goal is "stay at or below the target". Targets are the viewer's own choices, kept
 * in this browser only (localStorage); they are never sent anywhere. PUE and outlet temperature start from a labelled
 * default; energy and carbon have no sensible universal default, so they start unset rather than with an invented number.
 */

export type GoalId = "pue" | "outlet" | "energy" | "carbon";

export interface GoalDef {
  readonly id: GoalId;
  readonly label: string;
  readonly unit: string;
  readonly decimals: number;
  readonly min: number;
  readonly max: number;
  readonly step: number;
  readonly defaultTarget: number | null;
  /** Where the default comes from (shown next to an untouched default). */
  readonly defaultNote: string | null;
}

export const GOAL_DEFS: readonly GoalDef[] = [
  { id: "pue", label: "PUE", unit: "", decimals: 2, min: 1, max: 3, step: 0.01, defaultTarget: 1.3, defaultNote: "default target" },
  { id: "outlet", label: "Server outlet temperature", unit: "\u00b0C", decimals: 1, min: 20, max: 60, step: 0.5, defaultTarget: OUTLET_SCALE.warnAt, defaultNote: "default: the app\u2019s thermal warning level" },
  { id: "energy", label: "Total energy (24 h model)", unit: "kWh/day", decimals: 0, min: 1, max: 1_000_000, step: 100, defaultTarget: null, defaultNote: null },
  { id: "carbon", label: "Carbon (24 h model)", unit: "kg CO\u2082/day", decimals: 0, min: 1, max: 1_000_000, step: 100, defaultTarget: null, defaultNote: null },
];

export const GOAL_DEF_BY_ID: Readonly<Record<GoalId, GoalDef>> = Object.fromEntries(GOAL_DEFS.map((d) => [d.id, d])) as Record<GoalId, GoalDef>;

/** `null` = no target set. */
export type Goals = Readonly<Record<GoalId, number | null>>;

export const GOALS_KEY = "twingrid.executive-dashboard.goals.v1";

export function defaultGoals(): Goals {
  return Object.fromEntries(GOAL_DEFS.map((d) => [d.id, d.defaultTarget])) as Goals;
}

export function isValidTarget(id: GoalId, v: unknown): v is number {
  const d = GOAL_DEF_BY_ID[id];
  return typeof v === "number" && Number.isFinite(v) && v >= d.min && v <= d.max;
}

type StorageLike = Pick<Storage, "getItem" | "setItem">;

/** Never throws. A damaged or out-of-range entry falls back to that goal's default; unknown keys are ignored. */
export function loadGoals(storage: StorageLike | null): Goals {
  const out: Record<GoalId, number | null> = { ...defaultGoals() };
  try {
    const raw = storage?.getItem(GOALS_KEY);
    if (!raw) return out;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return out;
    for (const d of GOAL_DEFS) {
      if (!Object.prototype.hasOwnProperty.call(parsed, d.id)) continue;
      const v = (parsed as Record<string, unknown>)[d.id];
      if (v === null) out[d.id] = null;
      else if (isValidTarget(d.id, v)) out[d.id] = v;
    }
  } catch {
    /* storage unavailable or damaged: defaults */
  }
  return out;
}

/** Returns false when the browser refused the write (private mode, quota); the in-memory value still applies. */
export function saveGoals(goals: Goals, storage: StorageLike | null): boolean {
  try {
    if (!storage) return false;
    storage.setItem(GOALS_KEY, JSON.stringify(goals));
    return true;
  } catch {
    return false;
  }
}

export type ParsedTarget = { ok: true; value: number | null } | { ok: false; reason: string };

/** Empty text clears the target. Anything else must be a finite number inside the goal's bounds. */
export function parseTargetInput(id: GoalId, text: string): ParsedTarget {
  const d = GOAL_DEF_BY_ID[id];
  const t = text.trim();
  if (t === "") return { ok: true, value: null };
  const v = Number(t);
  if (!Number.isFinite(v)) return { ok: false, reason: "Enter a number." };
  if (!isValidTarget(id, v)) return { ok: false, reason: `Enter a value from ${d.min} to ${d.max}${d.unit ? ` ${d.unit}` : ""}.` };
  return { ok: true, value: v };
}

export type GoalStatus = "within" | "over" | "no-target" | "no-data";

export interface GoalView {
  readonly id: GoalId;
  readonly status: GoalStatus;
  /** 0..1 of the ring that is filled (value / target, capped at 1). */
  readonly fill: number;
  readonly value: number | null;
  readonly target: number | null;
}

/** "At or below the target" is within. A missing value or target is stated as such, never drawn as 0. */
export function goalView(id: GoalId, value: number | null, target: number | null): GoalView {
  if (value === null || !Number.isFinite(value)) return { id, status: "no-data", fill: 0, value: null, target };
  if (target === null) return { id, status: "no-target", fill: 0, value, target: null };
  return { id, status: value <= target ? "within" : "over", fill: Math.max(0, Math.min(1, value / target)), value, target };
}
