import { describe, expect, it } from "vitest";
import { CLAIM_FILTERS, GENERATED, NOT_RECORDED, claimGroup, countClaims, filterClaims, fmt, highestReward, type Claim, type PolicyRow } from "./data";

const claim = (id: string, kind: string): Claim => ({ id, kind: kind as Claim["kind"], text: `t ${id}`, evidence_paths: ["a.md"], limit: "l" });

describe("claim groups", () => {
  it("maps fact and result to supported, assumption to assumption, everything else to not supported", () => {
    expect(claimGroup("fact")).toBe("supported");
    expect(claimGroup("result")).toBe("supported");
    expect(claimGroup("assumption")).toBe("assumption");
    expect(claimGroup("hypothesis")).toBe("not-supported");
    expect(claimGroup("future")).toBe("not-supported");
    expect(claimGroup("something-new")).toBe("not-supported");
  });

  it("filters partition the ledger: the three groups add up to all", () => {
    const rows = [claim("C-01", "fact"), claim("C-02", "result"), claim("C-03", "assumption"), claim("C-04", "hypothesis"), claim("C-05", "future")];
    expect(filterClaims(rows, "all")).toHaveLength(5);
    expect(filterClaims(rows, "supported").map((c) => c.id)).toEqual(["C-01", "C-02"]);
    expect(filterClaims(rows, "assumption").map((c) => c.id)).toEqual(["C-03"]);
    expect(filterClaims(rows, "not-supported").map((c) => c.id)).toEqual(["C-04", "C-05"]);
    const parts = CLAIM_FILTERS.filter((f) => f.id !== "all").reduce((n, f) => n + countClaims(rows, f.id), 0);
    expect(parts).toBe(rows.length);
  });

  it("the generated ledger is non-empty and every row has the documented fields", () => {
    expect(GENERATED.claims.length).toBeGreaterThan(30);
    for (const c of GENERATED.claims) {
      expect(c.id).toMatch(/^C-\d{2,}$/);
      expect(c.text).not.toBe("");
      expect(c.limit).not.toBe("");
      expect(c.evidence_paths.length).toBeGreaterThan(0);
    }
  });
});

describe("helpers", () => {
  it("highestReward ignores policies without a numeric reward and returns null for none", () => {
    const rows: PolicyRow[] = [
      { policy: "a", total_reward: -5, energy_kwh: 1, water_L: 1, mean_pue: 1 },
      { policy: "b", total_reward: NOT_RECORDED, energy_kwh: 1, water_L: 1, mean_pue: 1 },
      { policy: "c", total_reward: -2, energy_kwh: 1, water_L: 1, mean_pue: 1 },
    ];
    expect(highestReward(rows)?.policy).toBe("c");
    expect(highestReward([rows[1]])).toBeNull();
    expect(highestReward([])).toBeNull();
  });

  it("fmt shows numbers to the given places and anything missing as 'not recorded'", () => {
    expect(fmt(-36.3272)).toBe("-36.33");
    expect(fmt(9414.4, 0)).toBe("9414");
    expect(fmt(NOT_RECORDED)).toBe(NOT_RECORDED);
    expect(fmt(undefined)).toBe(NOT_RECORDED);
    expect(fmt(Number.NaN)).toBe(NOT_RECORDED);
    expect(fmt("")).toBe(NOT_RECORDED);
  });
});
