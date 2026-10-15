import { describe, expect, it } from "vitest";
import {
  canDecide,
  canPropose,
  claimGate,
  decisionBlock,
  effectRows,
  ppoAvailability,
  proposalBody,
  recommendationQuery,
  sandboxQuery,
  setpointProblem,
  shadowBars,
  signed,
  type Context,
} from "./model";
import { EFFECT, passport, proposal } from "./testFixtures";

const CTX: Context = { utilisation: 0.65, outside_temp: 22, water_stress: 0.1, mode: "auto", chilled_water_temp: 10, inlet_temp_c: null };

describe("claim gate: PPO is never said to beat the baselines unless the stored decision is A", () => {
  it("allows the stored claim, verbatim, only for outcome A", () => {
    const text = "PPO met the pre-registered criterion (verbatim stored text).";
    const g = claimGate(passport({ outcome: "A", claim: text }));
    expect(g).toMatchObject({ allowed: true, claimText: text, outcome: "A" });
  });
  it("allows nothing for any other outcome, even when claim text is present", () => {
    for (const outcome of ["B", "C", "NOT_EVALUATED", "a", ""]) {
      const g = claimGate(passport({ outcome, claim: "PPO beats the baselines" }));
      expect(g.allowed).toBe(false);
      expect(g.claimText).toBeNull();
    }
  });
  it("an outcome A with an empty or 'none' claim allows nothing", () => {
    expect(claimGate(passport({ outcome: "A", claim: "   " })).allowed).toBe(false);
    expect(claimGate(passport({ outcome: "A", claim: "None" })).allowed).toBe(false);
  });
  it("no evaluation, no passport or no PPO entry means no claim", () => {
    expect(claimGate(passport({ noEvaluation: true }))).toMatchObject({ allowed: false, outcome: "NOT_EVALUATED" });
    expect(claimGate(undefined).allowed).toBe(false);
    expect(claimGate({ models: [] } as never).allowed).toBe(false);
  });
  it("keeps the stored text untouched (no trimming or rewording)", () => {
    const text = "  Spaced   text, exactly as stored.  ";
    expect(claimGate(passport({ outcome: "A", claim: text })).claimText).toBe(text);
  });
});

describe("PPO availability from the registry", () => {
  it("reports promoted or not, with the newest entry's status", () => {
    expect(ppoAvailability(passport({ loadable: true })).registryHasPromoted).toBe(true);
    const none = ppoAvailability(passport({ loadable: false }));
    expect(none.registryHasPromoted).toBe(false);
    expect(none.statusText).toBe("quarantined: no promoted policy");
    expect(ppoAvailability(undefined)).toEqual({ registryHasPromoted: false, statusText: null });
  });
});

describe("roles", () => {
  it("operators and admins propose; only admins decide", () => {
    expect([canPropose("viewer"), canPropose("operator"), canPropose("admin"), canPropose(null), canPropose("root")]).toEqual([false, true, true, false, false]);
    expect([canDecide("viewer"), canDecide("operator"), canDecide("admin"), canDecide(null)]).toEqual([false, false, true, false]);
  });
  it("an admin cannot decide their own or an already decided proposal", () => {
    expect(decisionBlock("admin", "admin1", proposal({ proposer: "operator1" }))).toBeNull();
    expect(decisionBlock("admin", "admin1", proposal({ proposer: "admin1" }))).toMatch(/someone else/);
    expect(decisionBlock("admin", "admin1", proposal({ status: "approved" }))).toMatch(/Already decided/);
    expect(decisionBlock("operator", "op2", proposal())).toMatch(/Only an admin/);
  });
});

describe("requests", () => {
  it("builds the recommendation and sandbox queries (inlet only when measured)", () => {
    expect(recommendationQuery(CTX)).toEqual({ utilisation: "0.65", outside_temp: "22", water_stress: "0.1", current_mode: "auto", current_chilled_water_temp: "10" });
    expect(recommendationQuery({ ...CTX, inlet_temp_c: 21.5 }).inlet_temp_c).toBe("21.5");
    expect(sandboxQuery(CTX, { chilled_water_temp_c: 9, cooling_mode: "free_air" })).toMatchObject({ proposed_chilled_water_temp: "9", proposed_mode: "free_air" });
  });
  it("builds the proposal body, trimming the rationale and omitting empty optionals", () => {
    const b = proposalBody(CTX, { chilled_water_temp_c: 11, cooling_mode: "hybrid" }, "  why  ");
    expect(b).toMatchObject({ chilled_water_temp_c: 11, cooling_mode: "hybrid", rationale: "why", current_mode: "auto" });
    expect("inlet_temp_c" in b).toBe(false);
    expect("rationale" in proposalBody(CTX, { chilled_water_temp_c: 11, cooling_mode: "hybrid" }, "  ")).toBe(false);
  });
  it("validates set-points before sending", () => {
    expect(setpointProblem({ chilled_water_temp_c: 11, cooling_mode: "hybrid" })).toBeNull();
    expect(setpointProblem({ chilled_water_temp_c: 4.9, cooling_mode: "hybrid" })).toMatch(/between 5 and 15/);
    expect(setpointProblem({ chilled_water_temp_c: 15.1, cooling_mode: "hybrid" })).toMatch(/between 5 and 15/);
    expect(setpointProblem({ chilled_water_temp_c: Number.NaN, cooling_mode: "hybrid" })).toMatch(/Enter/);
    expect(setpointProblem({ chilled_water_temp_c: 10, cooling_mode: "turbo" })).toMatch(/Choose a cooling mode/);
  });
});

describe("effect rows", () => {
  it("formats numbers and gives the direction in words", () => {
    const rows = Object.fromEntries(effectRows(EFFECT).map((r) => [r.key, r]));
    expect(rows.mean_pue).toMatchObject({ reference: "1.500", proposed: "1.400", delta: "−0.100", direction: "lower" });
    expect(rows.max_outlet_temp_C).toMatchObject({ delta: "+3.0", direction: "higher" });
    expect(effectRows({ ...EFFECT, delta: { ...EFFECT.delta, mean_pue: 0.0001 } }).find((r) => r.key === "mean_pue")).toMatchObject({ direction: "unchanged", delta: "0.000" });
    expect(signed(-2, 1)).toBe("−2.0");
  });
});

describe("shadow bars", () => {
  it("derives agree/differ counts from the summary", () => {
    expect(shadowBars({ n_samples: 8, agreement_rate: 0.75 })).toEqual({ total: 8, agree: 6, differ: 2, ratePct: "75.0" });
    expect(shadowBars({ n_samples: 0, agreement_rate: null })).toEqual({ total: 0, agree: 0, differ: 0, ratePct: null });
  });
});
