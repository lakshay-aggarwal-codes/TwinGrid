import { describe, expect, it } from "vitest";
import type { FreshnessState } from "@/telemetry/freshness";
import {
  attachCapture,
  buildIncidentReport,
  buildOperationalReport,
  buildReportProvenance,
  buildSimulationReport,
  buildSustainabilityReport,
  provenanceSection,
  reportToHtml,
  reportToMarkdown,
  type Report,
} from "./reports";
import { ALERTS, CFG, WHATIF, captureIn } from "./reportFixtures";

const row = (r: Report, item: string) => provenanceSection(r).rows!.find((x) => x.item === item)!;
const allText = (r: Report) => JSON.stringify(r.sections) + JSON.stringify(r.provenance.rows) + reportToMarkdown(r) + reportToHtml(r);

const operational = (state: FreshnessState, extra: Record<string, unknown> = {}) => {
  const { capture, liveState } = captureIn(state, extra);
  return { r: buildOperationalReport({ liveState, latestAnomaly: null, optimizeSummary: null }, capture), capture, liveState };
};

describe("provenance block is always present", () => {
  const builders: Array<[string, () => Report]> = [
    ["operational", () => operational("live").r],
    ["operational (no capture)", () => buildOperationalReport({ liveState: captureIn("live").liveState, latestAnomaly: null, optimizeSummary: null })],
    ["sustainability", () => buildSustainabilityReport(captureIn("live").liveState, captureIn("live").capture)],
    ["simulation", () => buildSimulationReport({ cfgA: CFG, cfgB: CFG, a: WHATIF, b: WHATIF, liveState: null })],
    ["incident", () => buildIncidentReport(ALERTS)],
    ["incident (empty list)", () => buildIncidentReport([])],
  ];

  it.each(builders)("%s: first section in Markdown and HTML, with every required field", (_n, make) => {
    const r = make();
    const md = reportToMarkdown(r);
    expect(md.indexOf("## Provenance")).toBeGreaterThan(-1);
    expect(md.indexOf("## Provenance")).toBeLessThan(md.indexOf(`## ${r.sections[0].title}`));
    expect(reportToHtml(r).indexOf("<h2>Provenance</h2>")).toBeLessThan(reportToHtml(r).indexOf(`<h2>${r.sections[0].title}`));
    const items = r.provenance.rows.map((x) => x.item);
    for (const k of ["Origin", "Scope", "Physics version", "Model version", "Detector", "Trained on", "Scenario id", "Run id", "Dataset", "Evaluation status", "Last updated — server time", "Last updated — simulated clock", "Freshness", "Fallback inputs", "Generated (browser time)"]) {
      expect(items).toContain(k);
    }
    expect(md).toMatch(/Generated \(browser time\): \d{4}-\d\d-\d\dT/);
  });

  it("no provenance value is blank, and gaps are stated as not reported / not available from backend", () => {
    const r = buildSimulationReport({ cfgA: CFG, cfgB: CFG, a: WHATIF, b: WHATIF, liveState: null });
    for (const x of r.provenance.rows) expect(x.value.trim()).not.toBe("");
    expect(row(r, "Run id").value).toBe("not available from backend");
    expect(row(r, "Scenario id").value).toBe("not available from backend");
    expect(row(r, "Physics version").value).toBe("not reported by backend");
    expect(row(r, "Origin").value).toBe("Unverified source (origin not reported by backend)");
  });
});

describe("browser time vs data time", () => {
  it("browser generation time is labelled 'browser time'; server time and simulated clock are separate rows", () => {
    const { r } = operational("live");
    expect(row(r, "Generated (browser time)").value).toBe("2026-10-06T15:00:00.000Z");
    expect(row(r, "Last updated — server time").value).toBe("2026-10-06 14:03:21 UTC");
    expect(row(r, "Last updated — simulated clock").value).toBe("2026-01-01 12:35:00");
    expect(row(r, "Last updated — simulated clock").source).toMatch(/not event time/);
  });

  it("the reading timestamp is labelled 'simulated clock' everywhere", () => {
    for (const r of [operational("live").r, buildSustainabilityReport(captureIn("live").liveState, captureIn("live").capture)]) {
      const notes = r.sections.map((s) => s.note ?? "").join("\n");
      expect(notes).toMatch(/Reading timestamp \(simulated clock, not event time\)/);
      expect(notes).not.toMatch(/reported by the backend: /);
    }
  });
});

describe("stale / disconnected feed at generation is stated first", () => {
  it.each([
    ["stale", /^STALE: .*stale \(last update 42 s ago\)\. Values are last known, not current\.$/],
    ["disconnected", /^DISCONNECTED: .*disconnected \(last data 42 s ago\)/],
    ["reconnecting", /^RECONNECTING: .*reconnecting \(last data 42 s ago\)/],
    ["unavailable", /^UNAVAILABLE: .*backend was unavailable/],
  ] as const)("%s", (state, re) => {
    const { r } = operational(state);
    expect(r.provenance.warnings).toHaveLength(1);
    expect(r.provenance.warnings[0]).toMatch(re);
    const md = reportToMarkdown(r);
    expect(md.split("\n").slice(0, 6).join("\n")).toContain("Data currency —");
    expect(reportToHtml(r)).toContain("Data currency —");
    expect(row(r, "Freshness").value).not.toBe("Live");
  });

  it("a live feed adds no warning; a live state with no frame says so; no capture says currency is unknown", () => {
    expect(operational("live").r.provenance.warnings).toEqual([]);
    const { liveState } = captureIn("live");
    const noFrame = buildOperationalReport({ liveState, latestAnomaly: null, optimizeSummary: null }, { frame: null, freshness: captureIn("live").capture.freshness, browserTime: new Date("2026-10-06T15:00:00Z") });
    expect(noFrame.provenance.warnings[0]).toMatch(/No live frame had been received/);
    const none = buildOperationalReport({ liveState, latestAnomaly: null, optimizeSummary: null });
    expect(none.provenance.warnings[0]).toMatch(/not captured/);
    expect(none.provenance.captured).toBe(false);
  });

  it("reports whose data is not from the feed (simulation, incident) carry no feed-currency warning", () => {
    expect(buildIncidentReport(ALERTS).provenance.warnings).toEqual([]);
    expect(buildSimulationReport({ cfgA: CFG, cfgB: CFG, a: WHATIF, b: WHATIF, liveState: null }).provenance.warnings).toEqual([]);
    expect(row(buildIncidentReport(ALERTS), "Freshness").value).toMatch(/not applicable/);
  });

  it("attachCapture stamps a capture-less report once, keeping its generation time, and is idempotent", () => {
    const { liveState, capture } = captureIn("stale");
    const bare = buildOperationalReport({ liveState, latestAnomaly: null, optimizeSummary: null });
    const stamped = attachCapture(bare, capture);
    expect(stamped.provenance.captured).toBe(true);
    expect(stamped.provenance.warnings[0]).toMatch(/^STALE/);
    expect(stamped.provenance.capturedFrom).toHaveLength(1);
    expect(stamped.generatedAt).toBe(bare.generatedAt);
    expect(row(stamped, "Generated (browser time)").value).toBe(bare.generatedAt);
    expect(attachCapture(stamped, captureIn("live").capture)).toBe(stamped);
  });
});

describe("origin and simulator-only", () => {
  it("simulated origin -> Simulator-only scope; absent origin -> Unverified; never Measured unless the payload says so", () => {
    expect(row(operational("live").r, "Scope").value).toMatch(/^Simulator-only/);
    const absent = operational("live", { origin: undefined }).r;
    expect(row(absent, "Origin").value).toMatch(/^Unverified source/);
    expect(row(absent, "Scope").value).toMatch(/^Unverified source/);
    expect(allText(absent)).not.toMatch(/measured telemetry\b(?!\.)|Measured\b/);
    expect(row(operational("live", { origin: "measured" }).r, "Origin").value).toBe("Measured");
    expect(row(operational("live", { origin: "Measured" }).r, "Origin").value).toMatch(/^Unverified/);
  });

  it("no section is titled 'Measured now' (a simulated reading never reads as measured)", () => {
    const { liveState } = captureIn("live");
    const r = buildSimulationReport({ cfgA: CFG, cfgB: CFG, a: WHATIF, b: WHATIF, liveState });
    expect(r.sections.map((s) => s.title).join("|")).not.toMatch(/Measured/);
    expect(r.sections.map((s) => s.title)).toContain("Live feed now (for reference, not part of either scenario)");
  });

  it("physics version, model version, detector and trained-on are printed when the backend supplied them", () => {
    const { r } = operational("live", { physics_version: "1.2.0" });
    expect(row(r, "Physics version").value).toBe("1.2.0");
    expect(row(r, "Model version").value).toBe("v3");
    expect(row(r, "Detector").value).toBe("ae-1");
    expect(row(r, "Trained on").value).toBe("synthetic");
  });
});

describe("sources", () => {
  it("anomaly rows are sourced WS /ws/live → anomaly_status, from the backend's status, with no client gauge", () => {
    const { r } = operational("live");
    const rows = r.sections.find((s) => s.title.startsWith("Anomaly"))!.rows!;
    expect(rows.map((x) => x.item)).toContain("Pipeline status");
    for (const x of rows) expect(x.source).toMatch(/^WS \/ws\/live → anomaly_status/);
    expect(rows.find((x) => x.item === "Score")!.value).toBe("0.0123");
    expect(rows.map((x) => x.item).join("|")).not.toMatch(/gauge/i);
  });

  it("no report mentions the deprecated /api/anomaly_score, in any serialisation", () => {
    const { liveState } = captureIn("live");
    const reports = [
      operational("live").r,
      buildOperationalReport({ liveState, latestAnomaly: { type: "spike", message: "m" }, optimizeSummary: { mean_pue: 1, mean_wue: 1, mean_cooling_power_kw: 1, total_water_consumed_L: 1, total_reward: 1, safety_violations: 0 } }),
      buildSustainabilityReport(liveState),
      buildSimulationReport({ cfgA: CFG, cfgB: CFG, a: WHATIF, b: WHATIF, liveState }),
      buildIncidentReport(ALERTS),
    ];
    for (const r of reports) expect(allText(r)).not.toContain("anomaly_score");
  });

  it("missing anomaly_status is 'not reported by backend', never a normal/zero reading", () => {
    const { r } = operational("live", { anomaly_status: undefined });
    const rows = r.sections.find((s) => s.title.startsWith("Anomaly"))!.rows!;
    expect(rows[0]).toMatchObject({ item: "Anomaly status", value: "not reported by backend" });
  });

  it("the optimisation run is stated as experimental and simulator-only in the provenance block", () => {
    const { liveState } = captureIn("live");
    const r = buildOperationalReport({ liveState, latestAnomaly: null, optimizeSummary: { mean_pue: 1.1, mean_wue: 0.2, mean_cooling_power_kw: 50, total_water_consumed_L: 9, total_reward: 3, safety_violations: 0 } });
    expect(row(r, "Optimisation run").value).toMatch(/simulator-only/);
  });
});

describe("incident counts", () => {
  it("are labelled 'in the list of N fetched'", () => {
    const r = buildIncidentReport(ALERTS);
    const summary = r.sections[0];
    expect(summary.note).toMatch(/in the list of 2 fetched/);
    const items = summary.rows!.map((x) => x.item);
    expect(items).toContain("Alerts fetched");
    expect(items).toContain("Severity WARNING (in the list of 2 fetched)");
    expect(items).toContain("Severity CRITICAL (in the list of 2 fetched)");
    expect(items).toContain("Acknowledged (in the list of 2 fetched)");
    expect(summary.rows!.find((x) => x.item.startsWith("Acknowledged"))!.value).toBe("1 of 2");
  });

  it("per-alert origin and model version are shown as reported, else 'not reported by backend'; no combined origin is computed", () => {
    const table = buildIncidentReport(ALERTS).sections[1].table!;
    expect(table.columns.slice(-2)).toEqual(["Origin", "Model version"]);
    expect(table.rows[0].slice(-2)).toEqual(["simulated", "v3"]);
    expect(table.rows[1].slice(-2)).toEqual(["not reported by backend", "not reported by backend"]);
  });
});

describe("carbon fallback logic is kept", () => {
  it("sustainability omits carbon rows on fallback and says so; real carbon is shown", () => {
    const fb = buildSustainabilityReport(captureIn("live", { carbon_data_is_real: false, carbon_intensity_gco2_per_kwh: 475 }).liveState);
    expect(fb.sections.map((s) => s.title)).not.toContain("Carbon (real grid data)");
    expect(fb.caveats.join(" ")).toMatch(/omitted from this report/);
    expect(row(fb, "Fallback inputs").value).toBe("carbon");
    const real = buildSustainabilityReport(captureIn("live", { carbon_data_is_real: true, carbon_intensity_gco2_per_kwh: 100, carbon_gco2: 5 }).liveState);
    expect(real.sections.map((s) => s.title)).toContain("Carbon (real grid data)");
    expect(row(real, "Fallback inputs").value).toBe("none");
  });
});

describe("buildReportProvenance", () => {
  it("is pure: same inputs, same output", () => {
    const { r, capture } = operational("stale");
    expect(JSON.stringify(buildReportProvenance(r.seed, capture, r.generatedAt))).toBe(JSON.stringify(buildReportProvenance(r.seed, capture, r.generatedAt)));
  });
});
