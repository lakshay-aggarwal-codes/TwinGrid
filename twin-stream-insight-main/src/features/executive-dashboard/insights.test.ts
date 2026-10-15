import { describe, expect, it } from "vitest";
import { MIN_SAMPLES, MIN_SPAN_MS, computeInsights, pctChange, readiness, RULE_BASED_LABEL } from "./insights";
import { defaultGoals, type Goals } from "./goals";
import { liveSamples, T0 } from "./testFixtures";

const noGoals: Goals = { pue: null, outlet: null, energy: null, carbon: null };
const text = (xs: { text: string }[]) => xs.map((x) => x.text);

/** 61 samples, 3 s apart = 3 min. First fifth (12) mean vs last fifth (12) mean differ by the stated step. */
const RISING_PUE = liveSamples(61, (i) => ({ pue: i < 12 ? 1.2 : i >= 49 ? 1.26 : 1.23, itKw: i < 12 ? 400 : i >= 49 ? 376 : 390, coolingKw: i < 12 ? 100 : i >= 49 ? 101 : 100 }));

describe("readiness", () => {
  it("needs both enough samples and enough span", () => {
    expect(readiness(liveSamples(MIN_SAMPLES - 1)).ready).toBe(false);
    expect(readiness(liveSamples(MIN_SAMPLES, () => ({}), 3000)).ready).toBe(false); // 27 s
    expect(readiness(liveSamples(MIN_SAMPLES, () => ({}), MIN_SPAN_MS / (MIN_SAMPLES - 1))).ready).toBe(true);
    expect(readiness([])).toEqual({ ready: false, samples: 0, spanMs: 0 });
  });
});

describe("pctChange", () => {
  it("is relative to the starting value and undefined at 0", () => {
    expect(pctChange(1.2, 1.26)).toBeCloseTo(5, 10);
    expect(pctChange(400, 376)).toBeCloseTo(-6, 10);
    expect(pctChange(0, 5)).toBeNull();
  });
});

describe("pue-trend", () => {
  it("states a rise, the two figures, the largest move and that it is not a cause", () => {
    const out = computeInsights({ samples: RISING_PUE, goals: noGoals, alerts: null });
    const trend = out.find((i) => i.id === "pue-trend");
    expect(trend?.text).toBe(
      "PUE rose 5.0% over the last 3 min (1.20 \u2192 1.26). Largest move in the same window: IT power \u22126.0% (cooling power +1.0%). This is an association, not a proven cause.",
    );
    expect(trend?.rule).toBe("pue-trend");
    expect(trend?.window).toBe("10:00:00 UTC to 10:03:00 UTC (3 min, 61 live samples received in this browser session)");
  });

  it("states a fall without naming drivers when IT and cooling power both moved less than 1%", () => {
    const s = liveSamples(61, (i) => ({ pue: i < 12 ? 1.3 : i >= 49 ? 1.2 : 1.25 }));
    const t = computeInsights({ samples: s, goals: noGoals, alerts: null }).find((i) => i.id === "pue-trend");
    expect(t?.text).toBe("PUE fell 7.7% over the last 3 min (1.30 \u2192 1.20). IT power and cooling power each moved less than 1% in the same window.");
  });

  it("calls a small move steady and adds no driver sentence", () => {
    const s = liveSamples(61, (i) => ({ pue: i < 12 ? 1.25 : i >= 49 ? 1.26 : 1.255 }));
    const t = computeInsights({ samples: s, goals: noGoals, alerts: null }).find((i) => i.id === "pue-trend");
    expect(t?.text).toBe("PUE was steady (within 2%) over the last 3 min (1.25 \u2192 1.26).");
  });

  it("produces no trend before there is enough live data", () => {
    expect(computeInsights({ samples: liveSamples(5), goals: defaultGoals(), alerts: null }).map((i) => i.id)).toEqual(["carbon-basis"]);
  });
});

describe("targets", () => {
  it("pue above target is an attention item and sorts first", () => {
    const out = computeInsights({ samples: RISING_PUE, goals: { ...noGoals, pue: 1.25 }, alerts: null });
    expect(out[0].id).toBe("pue-goal");
    expect(out[0].severity).toBe("attention");
    expect(out[0].text).toBe("PUE 1.26 is above your target of 1.25 (+0.8%).");
    expect(out[0].window).toBe("latest live sample, 10:03:00 UTC");
  });

  it("pue within target", () => {
    const out = computeInsights({ samples: RISING_PUE, goals: { ...noGoals, pue: 1.3 }, alerts: null });
    expect(out.find((i) => i.id === "pue-goal")?.text).toBe("PUE 1.26 is within your target of 1.30.");
    expect(out.find((i) => i.id === "pue-goal")?.severity).toBe("info");
  });

  it("outlet temperature uses the peak of the window", () => {
    const s = liveSamples(61, (i) => ({ outletC: i === 30 ? 39.2 : 30 }));
    const over = computeInsights({ samples: s, goals: { ...noGoals, outlet: 38 }, alerts: null }).find((i) => i.id === "outlet-goal");
    expect(over?.text).toBe("Server outlet temperature peaked at 39.2 \u00b0C in the last 3 min, above your target of 38.0 \u00b0C.");
    expect(over?.severity).toBe("attention");
    const within = computeInsights({ samples: s, goals: { ...noGoals, outlet: 40 }, alerts: null }).find((i) => i.id === "outlet-goal");
    expect(within?.text).toBe("Server outlet temperature stayed at or below 39.2 \u00b0C in the last 3 min, within your target of 40.0 \u00b0C.");
  });

  it("no target set -> no target statement", () => {
    const ids = computeInsights({ samples: RISING_PUE, goals: noGoals, alerts: null }).map((i) => i.id);
    expect(ids).not.toContain("pue-goal");
    expect(ids).not.toContain("outlet-goal");
  });
});

describe("alerts and carbon basis", () => {
  it("counts unacknowledged alerts and says no rack is attributed", () => {
    const a = computeInsights({ samples: [], goals: noGoals, alerts: { open: 3, listed: 50 } });
    expect(text(a)).toEqual(["3 unacknowledged alerts among the last 50 recorded. The backend attributes no alert to a rack."]);
    expect(a[0].window).toBe("last 50 recorded alerts");
    expect(text(computeInsights({ samples: [], goals: noGoals, alerts: { open: 1, listed: 4 } }))[0]).toContain("1 unacknowledged alert among");
    expect(computeInsights({ samples: [], goals: noGoals, alerts: { open: 0, listed: 4 } })).toEqual([]);
  });

  it("states the fallback carbon intensity only when the backend says it is not real", () => {
    const fb = computeInsights({ samples: liveSamples(3), goals: noGoals, alerts: null });
    expect(text(fb)).toEqual(["Carbon figures use a flat fallback intensity of 475 gCO\u2082/kWh. It is an assumption, not grid data."]);
    expect(computeInsights({ samples: liveSamples(3, () => ({ carbonReal: true })), goals: noGoals, alerts: null })).toEqual([]);
    expect(computeInsights({ samples: liveSamples(3, () => ({ carbonReal: null })), goals: noGoals, alerts: null })).toEqual([]);
  });
});

describe("determinism and shape", () => {
  it("same input, same output; attention before info; every item has a rule and a window", () => {
    const input = { samples: RISING_PUE, goals: { ...noGoals, pue: 1.25 }, alerts: { open: 2, listed: 50 } };
    const a = computeInsights(input);
    expect(computeInsights(input)).toEqual(a);
    expect(a.map((i) => i.severity)).toEqual(["attention", "attention", "info", "info"]);
    expect(a.map((i) => i.id)).toEqual(["pue-goal", "open-alerts", "pue-trend", "carbon-basis"]);
    for (const i of a) {
      expect(i.rule).not.toBe("");
      expect(i.window).not.toBe("");
    }
    expect(RULE_BASED_LABEL).toBe("Rule-based, not AI");
    expect(T0).toBeGreaterThan(0);
  });
});
