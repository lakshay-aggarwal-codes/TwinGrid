/**
 * Task 22: the printable executive / ESG report, as data. PURE. Every figure is copied from the latest live frame the
 * browser holds (nothing is estimated, interpolated or filled), and every row names the field it came from.
 * No `@/` value imports on purpose: this module is exercised directly by plain-node checks.
 */
import type { LiveStatePayload } from "@/api/models";
import { utcIso } from "./exportTable";

export interface ReportFeedState {
  readonly state: "connecting" | "live" | "stale" | "disconnected" | "reconnecting" | "unavailable";
  /** Milliseconds since the last frame (browser monotonic), or null. */
  readonly ageMs: number | null;
}

export interface ReportRow {
  readonly section: string;
  readonly item: string;
  readonly value: string;
  readonly unit: string;
  /** Field of the live frame this value was read from. */
  readonly source: string;
}

export interface PrintableReport {
  readonly title: string;
  readonly generatedAtUtc: string;
  /** Wording that applies to the whole document and is shown above the data (stale feed, no frame). */
  readonly banners: readonly string[];
  readonly rows: readonly ReportRow[];
  /** One sentence naming how carbon was obtained; always present. */
  readonly carbonLabel: string;
  readonly claimBoundary: readonly string[];
  /** Printed at the end of the document and repeated on every printed page. */
  readonly provenanceFooter: readonly { readonly label: string; readonly value: string }[];
  readonly hasData: boolean;
}

export const NOT_REPORTED = "not reported by backend";
export const SIMULATED_LABEL = "Simulated data";

export const CLAIM_BOUNDARY: readonly string[] = [
  "This is a simulation-based digital twin. Every value in this report comes from the platform's simulator, not from a real facility.",
  "Figures are model outputs. They are not measured, not validated against real data, and no calibration to a physical site is claimed.",
  "This document is not an audited emissions or ESG disclosure and must not be presented as one.",
];

const num = (v: number | undefined, digits: number): string => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : NOT_REPORTED);

export function carbonLabelFor(s: Pick<LiveStatePayload, "carbon_data_is_real" | "carbon_intensity_gco2_per_kwh"> | null): string {
  if (!s || s.carbon_data_is_real === undefined) return "Carbon: not reported by the backend, so no carbon figure is stated.";
  if (s.carbon_data_is_real === true) {
    return "Carbon: hour-of-day average of a loaded carbon-intensity series, not a live grid feed. Emissions are modelled from it.";
  }
  const v = typeof s.carbon_intensity_gco2_per_kwh === "number" ? `${s.carbon_intensity_gco2_per_kwh.toFixed(0)} gCO₂/kWh ` : "";
  return `Carbon: ASSUMPTION. A flat ${v}fallback intensity, identical at every hour and place, not real grid data (no carbon-intensity dataset is loaded on the backend). Emissions below are modelled from this assumed figure.`;
}

function feedBanner(feed: ReportFeedState | null, hasFrame: boolean): string[] {
  if (!hasFrame) return ["No live frame had been received when this report was generated, so it contains no data."];
  if (!feed) return ["The state of the live feed at generation was not captured, so how current these values are is unknown."];
  const age = feed.ageMs === null ? "" : ` (last update ${Math.round(feed.ageMs / 1000)} s before generation)`;
  switch (feed.state) {
    case "live":
      return [];
    case "stale":
      return [`STALE: the live feed was stale at generation${age}. Values are last known, not current.`];
    case "disconnected":
      return [`DISCONNECTED: the live feed was disconnected at generation${age}. Values are last known, not current.`];
    case "reconnecting":
      return [`RECONNECTING: the live feed was reconnecting at generation${age}. Values are last known, not current.`];
    case "unavailable":
      return ["UNAVAILABLE: the backend was unavailable at generation. Values are last known, not current."];
    default:
      return ["The live feed was still connecting at generation; values may be incomplete."];
  }
}

export function buildPrintableReport(input: {
  readonly frame: LiveStatePayload | null;
  readonly feed: ReportFeedState | null;
  readonly generatedAt: Date;
}): PrintableReport {
  const { frame: s, feed, generatedAt } = input;
  const rows: ReportRow[] = [];
  const add = (section: string, item: string, value: string, unit: string, source: string) => rows.push({ section, item, value, unit, source });

  if (s) {
    add("Efficiency", "PUE", num(s.pue, 2), "", "pue");
    add("Efficiency", "IT power", num(s.it_power_kw, 1), "kW", "it_power_kw");
    add("Efficiency", "Cooling power", num(s.cooling_power_kw, 1), "kW", "cooling_power_kw");
    add("Efficiency", "Total power", num(s.total_power_kw, 1), "kW", "total_power_kw");
    add("Efficiency", "Cooling mode", s.cooling_mode || NOT_REPORTED, "", "cooling_mode");
    add("Water", "WUE", num(s.wue, 3), "L/kWh", "wue");
    add("Water", "Water consumed", num(s.water_consumed_L, 0), "L", "water_consumed_L");
    add("Water", "Water flow", num(s.water_flow_lpm, 1), "L/min", "water_flow_lpm");
    if (s.carbon_data_is_real !== undefined) {
      const assumed = s.carbon_data_is_real === true ? "" : " (assumed fallback)";
      add("Carbon", `Carbon intensity${assumed}`, num(s.carbon_intensity_gco2_per_kwh, 0), "gCO₂/kWh", "carbon_intensity_gco2_per_kwh");
      add("Carbon", `Emissions this step${s.carbon_data_is_real === true ? "" : " (modelled from the assumed intensity)"}`, num(s.carbon_gco2, 0), "gCO₂", "carbon_gco2");
    }
  }

  const footer: { label: string; value: string }[] = [
    { label: "Data origin", value: s ? (s.origin ?? NOT_REPORTED) : NOT_REPORTED },
    { label: "Labelled", value: SIMULATED_LABEL },
    { label: "Frame time (simulated clock)", value: s ? (s.sim_time ?? s.timestamp ?? NOT_REPORTED) : NOT_REPORTED },
    { label: "Server ingest time (UTC)", value: s?.ts_ingest ? utcIso(s.ts_ingest) || NOT_REPORTED : NOT_REPORTED },
    { label: "Frame sequence", value: s?.seq === undefined ? NOT_REPORTED : String(s.seq) },
    { label: "Feed state at generation", value: feed ? feed.state : "not captured" },
    { label: "Anomaly detector trained on", value: s?.anomaly_status?.trained_on ?? NOT_REPORTED },
    { label: "Generated (UTC, browser clock)", value: utcIso(generatedAt) },
  ];

  return {
    title: "TwinGrid executive / ESG summary",
    generatedAtUtc: utcIso(generatedAt),
    banners: feedBanner(feed, s !== null),
    rows,
    carbonLabel: carbonLabelFor(s),
    claimBoundary: CLAIM_BOUNDARY,
    provenanceFooter: footer,
    hasData: s !== null,
  };
}
