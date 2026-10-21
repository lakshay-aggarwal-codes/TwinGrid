import { describe, expect, it } from "vitest";
import { DEFAULT_TARIFF, formatMoney, isDefaultTariff, parseStored, savingsWording, serialize, tariffQuery, toDraft, validateDraft } from "./tariff";

describe("validateDraft", () => {
  it("accepts the defaults and uppercases the currency", () => {
    const v = validateDraft({ ...toDraft(DEFAULT_TARIFF), currency: " eur " });
    expect(v.ok && v.tariff).toEqual({ ...DEFAULT_TARIFF, currency: "EUR" });
  });
  it("names every bad field and repairs none", () => {
    const v = validateDraft({ currency: "US", offPeakRate: "-1", peakRate: "abc", peakStartHour: "25", peakEndHour: "1.5", demandChargePerKw: "", billingDays: "0" });
    expect(v.ok).toBe(false);
    if (v.ok === false) expect(Object.keys(v.errors).sort()).toEqual(["billingDays", "currency", "demandChargePerKw", "offPeakRate", "peakEndHour", "peakRate", "peakStartHour"]);
  });
  it("refuses a rate above the backend limit", () => {
    expect(validateDraft({ ...toDraft(DEFAULT_TARIFF), peakRate: "1001" }).ok).toBe(false);
    expect(validateDraft({ ...toDraft(DEFAULT_TARIFF), peakRate: "1000" }).ok).toBe(true);
  });
});

describe("stored tariff", () => {
  it("round-trips", () => {
    const t = { ...DEFAULT_TARIFF, currency: "INR", peakRate: 9.5 };
    expect(parseStored(serialize(t))).toEqual(t);
  });
  it("falls back to the defaults for missing, damaged or out-of-range data", () => {
    expect(parseStored(null)).toBe(DEFAULT_TARIFF);
    expect(parseStored("{")).toBe(DEFAULT_TARIFF);
    expect(parseStored("[]")).toBe(DEFAULT_TARIFF);
    expect(parseStored(JSON.stringify({ ...DEFAULT_TARIFF, billingDays: 0 }))).toBe(DEFAULT_TARIFF);
  });
  it("knows when it is the default", () => {
    expect(isDefaultTariff(DEFAULT_TARIFF)).toBe(true);
    expect(isDefaultTariff({ ...DEFAULT_TARIFF, peakRate: 0.2 })).toBe(false);
  });
});

describe("tariffQuery", () => {
  it("uses the backend parameter names", () => {
    expect(tariffQuery(DEFAULT_TARIFF)).toEqual({
      currency: "USD", off_peak_rate: "0.08", peak_rate: "0.18", peak_start_hour: "16", peak_end_hour: "21", demand_charge_per_kw: "12", billing_days: "30",
    });
  });
});

describe("wording", () => {
  it("says saves / costs more / same in words", () => {
    expect(savingsWording(28.2, 10, "USD")).toEqual({ kind: "saves", text: "Saves $28.20 per day vs baseline (10.0 %)" });
    expect(savingsWording(-5, null, "USD")).toEqual({ kind: "costs-more", text: "Costs $5.00 more per day than baseline" });
    expect(savingsWording(0.001, 0, "USD").kind).toBe("same");
  });
  it("formats money and survives an unknown currency code", () => {
    expect(formatMoney(282, "USD")).toBe("$282.00");
    expect(formatMoney(1.5, "not-a-code")).toBe("1.50 not-a-code");
  });
});
