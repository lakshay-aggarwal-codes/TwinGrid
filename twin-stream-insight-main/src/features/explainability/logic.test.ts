import { describe, expect, it } from "vitest";
import {
  ExplanationSchema,
  PassportSchema,
  SYNTHETIC_LABEL,
  deviationSentence,
  featureLabel,
  formatMetric,
  kindLabel,
  liveWhy,
  metricLabel,
  modelsFor,
  scoreSentence,
  statusView,
  type FeatureDeviation,
} from "./model";
import passportJson from "./fixtures/passport.json";
import explanationJson from "./fixtures/explanation.json";

// The two fixtures are real backend output (src/model_passport.py and src/alert_explain.py run on the shipped registry
// and detector config), so these tests also prove the schemas accept what the backend sends.
const passport = PassportSchema.parse(passportJson);
const explanation = ExplanationSchema.parse(explanationJson);

const feat = (over: Partial<FeatureDeviation>): FeatureDeviation => ({
  feature: "server_outlet_temp_C", value: 55, train_min: 30, train_max: 50, position: 1.25, centre_distance: 1.5, outside_range_by: 0.25, outside_range: true, rank: 1, ...over,
}); // prettier-ignore

describe("passport payload", () => {
  it("parses the real backend body: one entry per registry artifact, every one a synthetic-data result", () => {
    expect(passport.models.length).toBe(8);
    expect(passport.metrics_label).toBe(SYNTHETIC_LABEL);
    for (const m of passport.models) {
      expect(m.data_origin).toBe("synthetic");
      expect(m.metrics_label).toBe(SYNTHETIC_LABEL);
      expect(m.claim_boundary.length).toBeGreaterThan(0);
    }
  });

  it("rejects a body that is not schema version 1 or lacks a required field (never repaired)", () => {
    expect(PassportSchema.safeParse({ ...passportJson, schema_version: 2 }).success).toBe(false);
    expect(PassportSchema.safeParse({ ...passportJson, models: [{ model_id: "x" }] }).success).toBe(false);
  });

  it("filters by kind and keeps registry order", () => {
    expect(modelsFor(passport, "anomaly").map((m) => m.kind)).toEqual(["anomaly"]);
    expect(modelsFor(passport, "ppo").length).toBe(6);
    expect(modelsFor(passport, null).length).toBe(8);
    expect(modelsFor(passport, "mystery")).toEqual([]);
  });

  it("PPO state is the stored decision, and a candidate shows no metric", () => {
    const cand = passport.models.find((m) => m.model_id === "ppo-p1-e2-cd2345024-s0")!;
    expect(cand.evaluation?.outcome).toBe("NOT_EVALUATED");
    expect(cand.evaluation?.claim_allowed).toBe("none");
    expect(cand.headline_metrics).toEqual([]);
    expect(passport.models.find((m) => m.kind === "anomaly")!.evaluation).toBeNull();
  });
});

describe("wording helpers", () => {
  it("status text always states whether the API may load the model", () => {
    expect(statusView("promoted").text).toMatch(/may load/);
    for (const s of ["candidate", "quarantined", "rejected", "retired"]) expect(statusView(s).text).toMatch(/does not load/);
    expect(statusView("weird")).toEqual({ icon: "unknown", text: 'Status "weird" (not recognised by this page)' });
  });

  it("kind and metric labels fall back to the raw name, never an invented one", () => {
    expect(kindLabel("anomaly")).toBe("Anomaly detector");
    expect(kindLabel("x")).toBe('Model of kind "x"');
    expect(metricLabel("f1")).toBe("F1");
    expect(metricLabel("novel_metric")).toBe("novel_metric");
  });

  it("formatMetric keeps four significant digits and handles non-finite input", () => {
    expect(formatMetric(0.9230769230769231)).toBe("0.9231");
    expect(formatMetric(-2.267707427967431)).toBe("-2.268");
    expect(formatMetric(1)).toBe("1");
    expect(formatMetric(Number.NaN)).toBe("not a number");
  });

  it("feature labels use the unit table when it knows the field", () => {
    expect(featureLabel("server_outlet_temp_C")).toBe("Server outlet temperature (°C)");
    expect(featureLabel("unknown_field")).toBe("unknown_field");
  });
});

describe("explanation numbers (from the real backend body)", () => {
  it("ranks the outlier signals first and restates the backend's numbers", () => {
    expect(explanation.features!.map((f) => f.feature).slice(0, 2)).toEqual(["water_pressure_bar", "server_outlet_temp_C"]);
    expect(explanation.features![0]).toMatchObject({ rank: 1, outside_range: true });
    expect(explanation.score_vs_threshold!.ratio).toBeCloseTo(2.4614, 4);
  });

  it("score sentence: ratio, relation to the threshold and the severity bound", () => {
    expect(scoreSentence({ score: 0.03, threshold: 0.01, ratio: 3, margin: 0.02, over_threshold: true, critical_above: 0.02, severity_by_rule: "CRITICAL" })).toBe(
      "Score 0.0300 is 3.00x the alert threshold 0.0100 (above it). The alert rule fires above the threshold; the severity rule says CRITICAL above 0.0200.",
    );
    expect(scoreSentence({ score: 0.005, threshold: 0.01, ratio: 0.5, margin: -0.005, over_threshold: false, critical_above: 0.02, severity_by_rule: "WARNING" })).toContain("(not above it)");
  });

  it("deviation sentence: outside the range vs inside it", () => {
    expect(deviationSentence(feat({}))).toBe("Server outlet temperature (°C) is 55.0: 25% of the range width above the top of the training range (30.0 to 50.0).");
    expect(deviationSentence(feat({ position: -0.5, outside_range_by: 0.5, value: 25 }))).toContain("50% of the range width below the bottom");
    expect(deviationSentence(feat({ position: 0.5, outside_range: false, outside_range_by: 0, value: 40 }))).toBe("Server outlet temperature (°C) is 40.0: 50% of the way through the training range (30.0 to 50.0).");
  });
});

describe("liveWhy: the detector's own shares from the live frame", () => {
  const ok = { total_error: 0.0421, top_feature: "water_pressure_bar", feature_contributions_pct: { water_flow_lpm: 10, water_pressure_bar: 62.5, server_outlet_temp_C: 20, it_power_kw: 5, humidity_pct: 2.5 } };

  it("sorts largest first and carries the backend's top feature and total error", () => {
    const w = liveWhy(ok)!;
    expect(w.shares.map((s) => s.feature)).toEqual(["water_pressure_bar", "server_outlet_temp_C", "water_flow_lpm", "it_power_kw", "humidity_pct"]);
    expect(w.top).toBe("water_pressure_bar");
    expect(w.totalError).toBeCloseTo(0.0421);
  });

  it("falls back to the largest share when top_feature is missing", () => {
    expect(liveWhy({ feature_contributions_pct: { a: 1, b: 3 } })!.top).toBe("b");
  });

  it.each([null, undefined, 5, "x", [], {}, { feature_contributions_pct: null }, { feature_contributions_pct: [] }, { feature_contributions_pct: {} }, { feature_contributions_pct: { a: -1 } }, { feature_contributions_pct: { a: "1" } }, { feature_contributions_pct: { a: Number.NaN } }])(
    "%j is no explanation (never a partial one)",
    (bad) => {
      expect(liveWhy(bad)).toBeNull();
    },
  );
});
