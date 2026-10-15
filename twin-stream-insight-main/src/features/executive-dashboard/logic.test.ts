import { describe, expect, it } from "vitest";
import type { LiveStatePayload } from "@/api/apiClient";
import { CAPTURED_BASELINES_ONLY, CAPTURED_LIST, clone, syntheticWithPpo } from "@/evaluation/testFixtures";
import { fmtSignedPct, fmtSpan, utcClock } from "./format";
import { GOALS_KEY, defaultGoals, goalView, loadGoals, parseTargetInput, saveGoals } from "./goals";
import { MAX_GAP_MS, MAX_SAMPLES, appendSample, sampleFromFrame, windowSamples } from "./liveSeries";
import { FALLBACK_CARBON_CAVEAT, buildSpark, carbonKpi, itEnergyKpi, itEnergyKwh, newestEvaluationId, pueKpi, savingsFacts, savingsKpi, totalEnergyKpi } from "./kpis";
import { REAL_WHATIF_05_30_02_CLOSED_9, REAL_WHATIF_065_22_04_AUTO_7, liveSamples } from "./testFixtures";

const mem = (init: Record<string, string> = {}) => {
  const m = { ...init };
  return { getItem: (k: string) => (k in m ? m[k] : null), setItem: (k: string, v: string) => void (m[k] = v) };
};

/** SYNTHETIC frame with round numbers. */
const frame = (over: Partial<LiveStatePayload> = {}): LiveStatePayload =>
  ({ pue: 1.25, it_power_kw: 400, cooling_power_kw: 100, total_power_kw: 500, server_outlet_temp_C: 30, carbon_intensity_gco2_per_kwh: 475, carbon_data_is_real: false, seq: 1, ...over }) as LiveStatePayload;

describe("format", () => {
  it("signed percent uses a real minus and never prints -0", () => {
    expect(fmtSignedPct(4.14)).toBe("+4.1%");
    expect(fmtSignedPct(-6)).toBe("\u22126.0%");
    expect(fmtSignedPct(-0.01)).toBe("0.0%");
  });
  it("spans and UTC clock", () => {
    expect(fmtSpan(45_000)).toBe("45 s");
    expect(fmtSpan(12 * 60_000)).toBe("12 min");
    expect(fmtSpan(65 * 60_000)).toBe("1 h 05 min");
    expect(fmtSpan(60 * 60_000)).toBe("1 h");
    expect(utcClock(Date.UTC(2026, 9, 15, 7, 5, 9))).toBe("07:05:09 UTC");
  });
});

describe("live series", () => {
  it("records finite frames only; a missing field is never filled with 0", () => {
    expect(sampleFromFrame(frame(), 5)).toMatchObject({ t: 5, seq: 1, pue: 1.25, itKw: 400, totalKw: 500, carbonReal: false });
    expect(sampleFromFrame(frame({ pue: Number.NaN }), 5)).toBeNull();
    expect(sampleFromFrame(frame({ it_power_kw: undefined as unknown as number }), 5)).toBeNull();
    expect(sampleFromFrame(frame({ carbon_intensity_gco2_per_kwh: undefined, carbon_data_is_real: undefined }), 5)).toMatchObject({ carbonGPerKwh: null, carbonReal: null });
    expect(sampleFromFrame(frame({ seq: undefined }), 5)?.seq).toBeNull();
  });

  it("ignores a duplicate seq and an out-of-order time", () => {
    const a = sampleFromFrame(frame({ seq: 1 }), 1000)!;
    const buf = appendSample([], a);
    expect(appendSample(buf, sampleFromFrame(frame({ seq: 1 }), 2000)!)).toBe(buf);
    expect(appendSample(buf, sampleFromFrame(frame({ seq: 2 }), 1000)!)).toBe(buf);
    expect(appendSample(buf, sampleFromFrame(frame({ seq: 2 }), 4000)!)).toHaveLength(2);
  });

  it("starts a new run after a long pause or a restarted sequence instead of bridging it", () => {
    const buf = appendSample([], sampleFromFrame(frame({ seq: 10 }), 1000)!);
    const afterPause = appendSample(buf, sampleFromFrame(frame({ seq: 11 }), 1000 + MAX_GAP_MS + 1)!);
    expect(afterPause).toHaveLength(1);
    expect(afterPause[0].seq).toBe(11);
    const restarted = appendSample(buf, sampleFromFrame(frame({ seq: 1 }), 4000)!);
    expect(restarted).toHaveLength(1);
    expect(restarted[0].seq).toBe(1);
    expect(appendSample(buf, sampleFromFrame(frame({ seq: 11 }), 1000 + MAX_GAP_MS)!)).toHaveLength(2);
  });

  it("is bounded", () => {
    let buf: readonly ReturnType<typeof liveSamples>[number][] = [];
    for (const s of liveSamples(MAX_SAMPLES + 25)) buf = appendSample(buf, s);
    expect(buf).toHaveLength(MAX_SAMPLES);
    expect(buf[0].seq).toBe(26);
  });

  it("windowSamples keeps the newest `windowMs`", () => {
    const s = liveSamples(11, () => ({}), 10_000);
    expect(windowSamples(s, 30_000).map((x) => x.seq)).toEqual([8, 9, 10, 11]);
    expect(windowSamples([], 1000)).toEqual([]);
  });
});

describe("goals", () => {
  it("PUE and outlet have labelled defaults; energy and carbon start unset", () => {
    const d = defaultGoals();
    expect(d.pue).toBe(1.3);
    expect(d.outlet).toBe(38);
    expect(d.energy).toBeNull();
    expect(d.carbon).toBeNull();
  });

  it("round-trips through storage and survives damage", () => {
    const s = mem();
    expect(saveGoals({ pue: 1.2, outlet: 36, energy: 12000, carbon: null }, s)).toBe(true);
    expect(loadGoals(s)).toEqual({ pue: 1.2, outlet: 36, energy: 12000, carbon: null });
    expect(loadGoals(mem({ [GOALS_KEY]: "{not json" }))).toEqual(defaultGoals());
    expect(loadGoals(mem({ [GOALS_KEY]: JSON.stringify({ pue: 99, outlet: "hot", energy: -1, carbon: 5000, extra: 1 }) }))).toEqual({ ...defaultGoals(), carbon: 5000 });
    expect(loadGoals(null)).toEqual(defaultGoals());
    expect(saveGoals(defaultGoals(), { getItem: () => null, setItem: () => { throw new Error("full"); } })).toBe(false);
    expect(saveGoals(defaultGoals(), null)).toBe(false);
  });

  it("parses target input: empty clears, text and out-of-range are refused", () => {
    expect(parseTargetInput("pue", " 1.25 ")).toEqual({ ok: true, value: 1.25 });
    expect(parseTargetInput("pue", "")).toEqual({ ok: true, value: null });
    expect(parseTargetInput("pue", "abc")).toEqual({ ok: false, reason: "Enter a number." });
    expect(parseTargetInput("pue", "0.5").ok).toBe(false);
    expect(parseTargetInput("energy", "1e9").ok).toBe(false);
    expect(parseTargetInput("outlet", "Infinity").ok).toBe(false);
  });

  it("goalView: within, over, no target, no data; the ring is capped", () => {
    expect(goalView("pue", 1.2, 1.3)).toMatchObject({ status: "within", fill: 1.2 / 1.3 });
    expect(goalView("pue", 1.3, 1.3).status).toBe("within");
    expect(goalView("pue", 1.5, 1.3)).toMatchObject({ status: "over", fill: 1 });
    expect(goalView("energy", 100, null)).toMatchObject({ status: "no-target", fill: 0 });
    expect(goalView("pue", null, 1.3).status).toBe("no-data");
    expect(goalView("pue", Number.NaN, 1.3).status).toBe("no-data");
  });
});

describe("KPIs", () => {
  it("IT energy is total water / WUE and equals the twin's own IT energy (real captures)", () => {
    expect(itEnergyKwh(REAL_WHATIF_065_22_04_AUTO_7)).toBeCloseTo(9480.000000000005, 6);
    expect(itEnergyKwh(REAL_WHATIF_05_30_02_CLOSED_9)).toBeCloseTo(8400.00000000003, 6);
  });

  it("IT energy is NOT MEASURED when WUE is 0, and no model run means NOT MEASURED", () => {
    const k = itEnergyKpi({ ...REAL_WHATIF_065_22_04_AUTO_7, wue: 0 });
    expect(k.value).toBeNull();
    expect(k.reason).toMatch(/WUE is 0/);
    expect(itEnergyKpi(null).value).toBeNull();
    expect(totalEnergyKpi(null).value).toBeNull();
    expect(carbonKpi(null).value).toBeNull();
    expect(pueKpi(null, null).value).toBeNull();
  });

  it("total energy and carbon are the backend numbers; fallback carbon is labelled and caveated", () => {
    expect(totalEnergyKpi(REAL_WHATIF_065_22_04_AUTO_7).value).toBe(12528.29816214626);
    const c = carbonKpi(REAL_WHATIF_065_22_04_AUTO_7);
    expect(c.value).toBe(5950.941627019469);
    expect(c.label).toBe("Carbon (fallback)");
    expect(c.caveat).toBe(FALLBACK_CARBON_CAVEAT);
    const real = carbonKpi({ ...REAL_WHATIF_065_22_04_AUTO_7, carbon_data_is_real: true });
    expect(real.label).toBe("Carbon");
    expect(real.caveat).toBeNull();
  });

  it("PUE is the latest live tick and names the model mean in its basis", () => {
    const k = pueKpi(liveSamples(1, () => ({ pue: 1.31 }))[0], REAL_WHATIF_065_22_04_AUTO_7);
    expect(k.value).toBe(1.31);
    expect(k.basis).toContain("1.32");
  });
});

describe("savings vs baseline controller", () => {
  it("real capture: rule vs best_constant, backend energy_kwh, claim status kept", () => {
    const f = savingsFacts(CAPTURED_BASELINES_ONLY)!;
    expect(f.baselineId).toBe("rule");
    expect(f.comparedId).toBe("best_constant");
    expect(f.savedKwh).toBeCloseTo(9929.62897635071 - 9649.784016285228, 9);
    expect(f.savedPct).toBeCloseTo(((9929.62897635071 - 9649.784016285228) / 9929.62897635071) * 100, 9);
    expect(f.claimAllowed).toBe("none");
    const k = savingsKpi(f);
    expect(k.value).toBeCloseTo(2.8183, 3);
    expect(k.direction).toBe("less energy than the baseline");
    expect(k.caveat).toMatch(/no performance claim/);
    expect(k.basis).toContain("claim allowed: none");
  });

  it("a PPO policy is preferred when the report has one (SYNTHETIC shape fixture)", () => {
    const r = syntheticWithPpo("A");
    const f = savingsFacts(r)!;
    expect(f.baselineId).toBe("rule");
    expect(/^ppo/i.test(f.comparedId)).toBe(true);
  });

  it("more energy than the baseline is stated in words with a positive magnitude", () => {
    const r = clone(CAPTURED_BASELINES_ONLY);
    r.policies[1].metrics.energy_kwh = 10_000;
    const k = savingsKpi(savingsFacts(r));
    expect(k.direction).toBe("more energy than the baseline");
    expect(k.value).toBeGreaterThan(0);
  });

  it("NOT MEASURED without a baseline, a second policy, or finite positive baseline energy", () => {
    const noRule = clone(CAPTURED_BASELINES_ONLY);
    noRule.policies = noRule.policies.filter((p) => p.policy_id !== "rule");
    expect(savingsFacts(noRule)).toBeNull();
    const only = clone(CAPTURED_BASELINES_ONLY);
    only.policies = only.policies.slice(0, 1);
    expect(savingsFacts(only)).toBeNull();
    const zero = clone(CAPTURED_BASELINES_ONLY);
    zero.policies[0].metrics.energy_kwh = 0;
    expect(savingsFacts(zero)).toBeNull();
    const missing = clone(CAPTURED_BASELINES_ONLY);
    delete missing.policies[1].metrics.energy_kwh;
    expect(savingsFacts(missing)).toBeNull();
    expect(savingsKpi(null).value).toBeNull();
    expect(savingsKpi(null, "why").reason).toBe("why");
  });

  it("newest report by generated_at_utc, undated last, ties keep list order", () => {
    expect(newestEvaluationId([])).toBeNull();
    expect(newestEvaluationId([{ evaluation_id: "a", generated_at_utc: "2026-10-01T00:00:00+00:00" }, { evaluation_id: "b", generated_at_utc: "2026-10-02T00:00:00+00:00" }])).toBe("b");
    expect(newestEvaluationId([{ evaluation_id: "a" }, { evaluation_id: "b", generated_at_utc: "2026-10-02T00:00:00+00:00" }])).toBe("b");
    expect(newestEvaluationId([{ evaluation_id: "a", generated_at_utc: "x" }, { evaluation_id: "b", generated_at_utc: "x" }])).toBe("a");
    expect(newestEvaluationId(CAPTURED_LIST.evaluations)).toBe(CAPTURED_LIST.evaluations[0].evaluation_id);
  });
});

describe("sparkline", () => {
  it("a plain polyline in order; flat series sits mid-height; fewer than two values is null", () => {
    expect(buildSpark([1], 120, 32)).toBeNull();
    expect(buildSpark([Number.NaN, 2], 120, 32)).toBeNull();
    const flat = buildSpark([5, 5, 5], 120, 32)!;
    expect(flat.path).toBe("M2 16 L60 16 L118 16");
    const up = buildSpark([0, 10], 120, 32)!;
    expect(up.path).toBe("M2 30 L118 2");
    expect(up).toMatchObject({ min: 0, max: 10, latest: 10, count: 2, last: { x: 118, y: 2 } });
  });
});
