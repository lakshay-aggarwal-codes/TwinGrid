import { describe, expect, it } from "vitest";
import { CarbonScheduleSchema } from "./schema";
import { flat, synthetic, unverified, varying } from "./testData";

describe("contract", () => {
  it("accepts each well-formed status, extra fields included", () => {
    for (const body of [varying(), flat(), unverified(), synthetic()]) expect(CarbonScheduleSchema.safeParse({ ...body, extra: 1 }).success).toBe(true);
  });
  it("rejects a saving or window claimed without a supporting status", () => {
    expect(CarbonScheduleSchema.safeParse({ ...flat(), savings: { emissions_kg: 5, pct: 3 } }).success).toBe(false);
    expect(CarbonScheduleSchema.safeParse({ ...unverified(), best: varying().best }).success).toBe(false);
    expect(CarbonScheduleSchema.safeParse({ ...flat(), baseline: varying().baseline }).success).toBe(false);
  });
  it("rejects an ok result with no window, baseline or saving", () => {
    expect(CarbonScheduleSchema.safeParse({ ...varying(), savings: null }).success).toBe(false);
    expect(CarbonScheduleSchema.safeParse({ ...varying(), best: null }).success).toBe(false);
  });
  it("only a synthetic result may carry the synthetic label, and it must", () => {
    expect(CarbonScheduleSchema.safeParse({ ...varying(), synthetic_label: "x" }).success).toBe(false);
    expect(CarbonScheduleSchema.safeParse({ ...synthetic(), synthetic_label: null }).success).toBe(false);
    expect(CarbonScheduleSchema.safeParse({ ...synthetic(), profile: "data" }).success).toBe(false);
  });
  it("rejects an unknown status, a short curve and a non-finite number", () => {
    expect(CarbonScheduleSchema.safeParse({ ...varying(), status: "great" }).success).toBe(false);
    expect(CarbonScheduleSchema.safeParse({ ...varying(), curve_gco2_per_kwh: [1, 2, 3] }).success).toBe(false);
    expect(CarbonScheduleSchema.safeParse({ ...varying(), best: { ...varying().best!, emissions_kg: Number.POSITIVE_INFINITY } }).success).toBe(false);
  });
});
