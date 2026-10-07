/**
 * Stage 13: report model, builders, and serializers.
 *
 * Every report is built ON DEMAND from data the app already holds from a real
 * API response, and every row names the endpoint + field it came from
 * (`source`), so "where did this number come from?" always has a concrete
 * answer. Builders only reformat those values -- they never estimate,
 * interpolate, or fill gaps, and they contain no narrative text beyond fixed
 * labels and the caveats below (same rule as the Operations Console: no
 * invented analysis, since there is no LLM behind this app).
 *
 * Output form (decided + documented here): reports render in-app (see
 * components/shell/ReportDialog.tsx), and can be downloaded as Markdown or
 * printed / saved as PDF via the browser. No document-generation library is
 * used -- the smallest thing that satisfies "in-app view + exportable".
 */
import type {
  AlertRecord,
  AnomalyStatusPayload,
  LiveStatePayload,
  OptimizeSummary,
  StateResponse,
  WhatIfResponse,
} from "@/api/apiClient";
import type { LatestAnomaly, SimConfig } from "@/hooks/useSimulation";
import type { Freshness } from "@/telemetry/freshness";
import type { Stamped } from "@/telemetry/stamped";
import { buildProvenance, formatAge, type ProvenanceView } from "@/provenance";

export type ReportKind = "operational" | "simulation" | "incident" | "sustainability";

export interface ReportRow {
  item: string;
  value: string;
  /** Endpoint + field this value was read from. */
  source: string;
}

export interface ReportTable {
  columns: string[];
  rows: string[][];
}

export interface ReportSection {
  title: string;
  rows?: ReportRow[];
  table?: ReportTable;
  note?: string;
}

/**
 * FE-10: what the browser knew about the live feed at the moment of generation. Built from the feed store's stamped data only.
 * `browserTime` is the BROWSER clock and is only ever labelled as such; it is never data time.
 */
export interface ReportCapture {
  readonly frame: Stamped<LiveStatePayload> | null;
  readonly freshness: Freshness;
  readonly reconnectAttempt?: number | null;
  readonly browserTime: Date;
}

/** Facts a builder knows about its own data (everything else comes from the capture). Plain data, so a report can be re-stamped. */
export interface ProvenanceSeed {
  /** Values come from the live feed: a stale/disconnected feed at generation is stated at the top. */
  readonly usesLiveFeed: boolean;
  /** Origin / times / physics version are taken from the live payload below (false: the data has no feed origin). */
  readonly feed: {
    readonly origin?: string;
    readonly tsIngest?: string;
    readonly simTime?: string;
    readonly physicsVersion?: string;
    readonly anomaly?: Pick<AnomalyStatusPayload, "model_version" | "detector_id" | "trained_on"> | null;
  } | null;
  readonly inputsFallback: readonly string[];
  /** Scenario parameters / id text, or null when none apply. */
  readonly scenarioNote: string | null;
  /** Extra provenance rows (e.g. the optimisation run). */
  readonly extraRows: readonly ReportRow[];
  /** Where the origin row's value was read from. */
  readonly originSource: string;
}

export interface ReportProvenance {
  readonly view: ProvenanceView;
  /** false => no feed capture was available when this was built. */
  readonly captured: boolean;
  readonly capturedFrom: readonly Stamped<LiveStatePayload>[];
  /** Printed in the first lines of every export. */
  readonly warnings: readonly string[];
  /** The provenance block, as report rows. */
  readonly rows: readonly ReportRow[];
  /** Browser clock at generation. Labelled "browser time". */
  readonly browserTime: string;
}

export interface Report {
  kind: ReportKind;
  title: string;
  /** ISO timestamp of when this report was generated (BROWSER clock -- labelled "browser time" wherever shown). */
  generatedAt: string;
  /** FE-10: every report carries a provenance block; serializers always print it before the data sections. */
  provenance: ReportProvenance;
  seed: ProvenanceSeed;
  sections: ReportSection[];
  /** Honesty caveats that apply to this report (fallback data, missing
   * per-rack data, etc.). Always rendered, never collapsed. */
  caveats: string[];
}

const LIVE = "WS /ws/live → StateResponse";
const FACILITY_WIDE_CAVEAT =
  "All values are facility-wide. The backend has no per-rack or per-zone measurements, so nothing in this report is specific to an individual rack.";
const CARBON_FALLBACK_CAVEAT =
  "Carbon figures use a flat 475 gCO₂/kWh fallback, not real grid-intensity data (no carbon-intensity dataset is loaded on the backend).";

const f = (v: number, d: number) => v.toFixed(d);

// ---------------------------------------------------------------------------
// Provenance block (FE-10, roadmap section 16): the FE-05 view-model rendered as report rows
// ---------------------------------------------------------------------------

const NOT_REPORTED = "not reported by backend";
const NOT_AVAILABLE = "not available from backend";

const DETAIL_SOURCE: Record<string, string> = {
  quality: "not provided by the backend",
  source: "report endpoint class (frontend-known)",
  "server-time": "WS /ws/live → ts_ingest",
  "sim-clock": "WS /ws/live → sim_time (simulated clock, not event time)",
  "browser-receipt": "browser receipt age (monotonic clock; not data time)",
  freshness: "feed store state at generation",
  scenario: "not provided by the backend",
  run: "not provided by the backend",
  physics: "WS /ws/live → physics_version",
  model: "WS /ws/live → anomaly_status.model_version",
  detector: "WS /ws/live → anomaly_status.detector_id",
  "trained-on": "WS /ws/live → anomaly_status.trained_on",
  dataset: "not provided by the backend",
  "weather-plant": "not provided by the backend",
  evaluation: "not provided by the backend",
  calibration: "not provided by the backend",
  fallback: "carbon_data_is_real from the data shown",
};

function stateWarning(freshness: Freshness | null, captured: boolean, hasFrame: boolean): string[] {
  if (!captured || !freshness) {
    return ["Feed state at generation was not captured, so how current these values are is unknown."];
  }
  const age = freshness.ageMs === null ? null : formatAge(freshness.ageMs);
  switch (freshness.state) {
    case "live":
      return hasFrame ? [] : ["No live frame had been received when this report was generated."];
    case "stale":
      return [`STALE: generated while the live feed was stale${age ? ` (last update ${age})` : ""}. Values are last known, not current.`];
    case "disconnected":
      return [`DISCONNECTED: generated while the live feed was disconnected${age ? ` (last data ${age})` : ""}. Values are last known, not current.`];
    case "reconnecting":
      return [`RECONNECTING: generated while the live feed was reconnecting${age ? ` (last data ${age})` : ""}. Values are last known, not current.`];
    case "unavailable":
      return ["UNAVAILABLE: generated while the backend was unavailable. Values are last known, not current."];
    default:
      return ["No live frame had been received when this report was generated."];
  }
}

/** Pure. The provenance block for a report: same view-model as the UI, with "not reported by backend" for every gap. */
export function buildReportProvenance(seed: ProvenanceSeed, capture: ReportCapture | null | undefined, generatedAt: string): ReportProvenance {
  const frame = capture?.frame ?? null;
  const captured = capture != null;
  const feed = seed.feed;
  const view = buildProvenance({
    source: { kind: "report" },
    origin: feed?.origin,
    serverTime: feed?.tsIngest,
    simTime: feed?.simTime,
    physicsVersion: feed?.physicsVersion,
    modelVersion: feed?.anomaly?.model_version ?? undefined,
    detectorId: feed?.anomaly?.detector_id,
    trainedOn: feed?.anomaly?.trained_on,
    inputsFallback: [...seed.inputsFallback],
    freshness: seed.usesLiveFeed ? capture?.freshness : undefined,
    reconnectAttempt: capture?.reconnectAttempt,
  });

  const rows: ReportRow[] = view.detail.map((d) => {
    const raw = d.id === "scenario" || d.id === "run" ? (d.reported ? d.value : NOT_AVAILABLE) : d.value.replace(/not reported/g, NOT_REPORTED);
    const value = d.id === "freshness" && !seed.usesLiveFeed ? "not applicable (data is not from the live feed)" : raw;
    return {
      item: d.label,
      value,
      source: d.id === "origin" ? seed.originSource : (DETAIL_SOURCE[d.id] ?? NOT_REPORTED),
    };
  });
  const scope =
    view.origin.state === "simulated"
      ? "Simulator-only — values come from the physics simulator, not measured telemetry."
      : view.origin.state === "unverified"
        ? "Unverified source — these values are not presented as measured."
        : view.origin.text;
  rows.push({ item: "Scope", value: scope, source: "origin (as reported)" });
  if (seed.scenarioNote) rows.push({ item: "Scenario parameters", value: seed.scenarioNote, source: "Simulation Lab controls" });
  rows.push(...seed.extraRows);
  rows.push({ item: "Generated (browser time)", value: generatedAt, source: "browser clock at generation; not data time" });

  return {
    view,
    captured,
    capturedFrom: frame ? [frame] : [],
    warnings: seed.usesLiveFeed ? stateWarning(capture?.freshness ?? null, captured, frame !== null) : [],
    rows,
    browserTime: generatedAt,
  };
}

/** The provenance block as a section (the first one in every export). */
export function provenanceSection(r: Report): ReportSection {
  return {
    title: "Provenance",
    note: "Where these values came from. Fields the backend did not provide are stated as such.",
    rows: [...r.provenance.rows],
  };
}

/** Re-stamp a report with the feed state captured at generation (used when the builder was not given a capture). */
export function attachCapture(report: Report, capture: ReportCapture): Report {
  if (report.provenance.captured) return report;
  return { ...report, provenance: buildReportProvenance(report.seed, { ...capture, browserTime: new Date(report.generatedAt) }, report.generatedAt) };
}

function finish(
  base: Pick<Report, "kind" | "title" | "sections" | "caveats">,
  seed: ProvenanceSeed,
  capture: ReportCapture | null | undefined,
): Report {
  const generatedAt = (capture?.browserTime ?? new Date()).toISOString();
  return { ...base, generatedAt, seed, provenance: buildReportProvenance(seed, capture, generatedAt) };
}

function feedSeedOf(s: LiveStatePayload): NonNullable<ProvenanceSeed["feed"]> {
  return {
    origin: s.origin,
    tsIngest: s.ts_ingest,
    simTime: s.sim_time,
    physicsVersion: (s as { physics_version?: string }).physics_version,
    anomaly: s.anomaly_status ?? null,
  };
}

// ---------------------------------------------------------------------------
// Operational
// ---------------------------------------------------------------------------

export interface OperationalInput {
  /** The latest live payload (anomaly_status, origin and times ride on it). */
  liveState: StateResponse | LiveStatePayload;
  /** @deprecated Not used. The gauge was a client-side normalisation; the report prints the backend's anomaly_status instead. */
  anomalyGauge?: number;
  latestAnomaly: LatestAnomaly | null;
  /** Most recent PPO evaluation run from the Operations Console this session. */
  optimizeSummary: OptimizeSummary | null;
}

const ANOMALY = "WS /ws/live → anomaly_status";

export function buildOperationalReport(input: OperationalInput, capture?: ReportCapture | null): Report {
  const { liveState: s, latestAnomaly, optimizeSummary } = input;
  const live = s as LiveStatePayload;
  const a = live.anomaly_status;

  const anomalyRows: ReportRow[] = a
    ? [
        { item: "Pipeline status", value: String(a.status), source: `${ANOMALY}.status` },
        { item: "Score", value: a.score === null ? "not scored" : a.score.toFixed(4), source: `${ANOMALY}.score` },
        { item: "Detector threshold", value: a.threshold === null ? "not reported by backend" : a.threshold.toFixed(4), source: `${ANOMALY}.threshold` },
        { item: "Type", value: a.type ?? "none", source: `${ANOMALY}.type` },
        {
          item: "Window filled",
          value: a.window_filled !== undefined && a.window_size !== undefined ? `${a.window_filled} of ${a.window_size}` : "not reported by backend",
          source: `${ANOMALY}.window_filled / window_size`,
        },
      ]
    : [{ item: "Anomaly status", value: "not reported by backend", source: ANOMALY }];
  anomalyRows.push({
    item: "Most recent anomaly episode this session",
    value: latestAnomaly ? `${latestAnomaly.type} — ${latestAnomaly.message}` : "None received",
    source: `${ANOMALY} (type, message; first frame of each episode)`,
  });

  const sections: ReportSection[] = [
    {
      title: "Facility state (latest live reading)",
      note: `Reading timestamp (simulated clock, not event time): ${s.timestamp}`,
      rows: [
        { item: "PUE", value: f(s.pue, 2), source: `${LIVE}.pue` },
        { item: "WUE (L/kWh)", value: f(s.wue, 3), source: `${LIVE}.wue` },
        { item: "Cooling mode", value: s.cooling_mode, source: `${LIVE}.cooling_mode` },
        { item: "Server utilisation", value: f(s.server_utilisation, 1), source: `${LIVE}.server_utilisation` },
        { item: "IT power (kW)", value: f(s.it_power_kw, 0), source: `${LIVE}.it_power_kw` },
        { item: "Cooling power (kW)", value: f(s.cooling_power_kw, 0), source: `${LIVE}.cooling_power_kw` },
        { item: "Total power (kW)", value: f(s.total_power_kw, 0), source: `${LIVE}.total_power_kw` },
        { item: "Server inlet temp (°C)", value: f(s.server_inlet_temp_C, 1), source: `${LIVE}.server_inlet_temp_C` },
        { item: "Server outlet temp (°C)", value: f(s.server_outlet_temp_C, 1), source: `${LIVE}.server_outlet_temp_C` },
        { item: "Outside temp (°C)", value: f(s.outside_temp_C, 1), source: `${LIVE}.outside_temp_C` },
        { item: "Humidity (%)", value: f(s.humidity_pct, 1), source: `${LIVE}.humidity_pct` },
        { item: "Water flow (L/min)", value: f(s.water_flow_lpm, 1), source: `${LIVE}.water_flow_lpm` },
        { item: "Water pressure (bar)", value: f(s.water_pressure_bar, 2), source: `${LIVE}.water_pressure_bar` },
        { item: "Water consumed (L)", value: f(s.water_consumed_L, 0), source: `${LIVE}.water_consumed_L` },
      ],
    },
    { title: "Anomaly detector (server-side)", note: "Reported by the backend's anomaly pipeline; the browser does not score anything.", rows: anomalyRows },
  ];

  const extraRows: ReportRow[] = [];
  if (optimizeSummary) {
    const o = optimizeSummary;
    extraRows.push({
      item: "Optimisation run",
      value: "Experimental; simulator-only. Evaluation of the trained PPO policy, not a control action on a real facility.",
      source: "POST /api/optimize",
    });
    sections.push({
      title: "Most recent cooling optimization run (this session; experimental, simulator-only)",
      note: "Result of a 24h evaluation of the trained PPO policy, triggered from the Operations Console.",
      rows: [
        { item: "Mean PUE", value: f(o.mean_pue, 2), source: "POST /api/optimize → summary.mean_pue" },
        { item: "Mean WUE", value: f(o.mean_wue, 3), source: "POST /api/optimize → summary.mean_wue" },
        { item: "Mean cooling power (kW)", value: f(o.mean_cooling_power_kw, 0), source: "POST /api/optimize → summary.mean_cooling_power_kw" },
        { item: "Total water consumed (L)", value: f(o.total_water_consumed_L, 0), source: "POST /api/optimize → summary.total_water_consumed_L" },
        { item: "Total reward", value: f(o.total_reward, 1), source: "POST /api/optimize → summary.total_reward" },
        { item: "Safety violations", value: String(o.safety_violations), source: "POST /api/optimize → summary.safety_violations" },
      ],
    });
  }

  const caveats = [FACILITY_WIDE_CAVEAT];
  if (s.carbon_data_is_real === false) caveats.push(CARBON_FALLBACK_CAVEAT);

  const seed: ProvenanceSeed = {
    usesLiveFeed: true,
    feed: feedSeedOf(live),
    inputsFallback: s.carbon_data_is_real === false ? ["carbon"] : [],
    scenarioNote: null,
    extraRows,
    originSource: "WS /ws/live → origin",
  };
  return finish({ kind: "operational", title: "Operational report", sections, caveats }, seed, capture);
}

// ---------------------------------------------------------------------------
// Sustainability
// ---------------------------------------------------------------------------

export function buildSustainabilityReport(s: StateResponse | LiveStatePayload, capture?: ReportCapture | null): Report {
  const rows: ReportRow[] = [
    { item: "WUE (L/kWh)", value: f(s.wue, 3), source: `${LIVE}.wue` },
    { item: "Water consumed (L)", value: f(s.water_consumed_L, 0), source: `${LIVE}.water_consumed_L` },
    { item: "Water flow (L/min)", value: f(s.water_flow_lpm, 1), source: `${LIVE}.water_flow_lpm` },
    { item: "PUE", value: f(s.pue, 2), source: `${LIVE}.pue` },
    { item: "Cooling mode", value: s.cooling_mode, source: `${LIVE}.cooling_mode` },
  ];
  if (s.water_stress !== undefined) {
    rows.push({ item: "Water stress index", value: f(s.water_stress, 2), source: `${LIVE}.water_stress` });
  }
  if (s.drought_override_active !== undefined) {
    rows.push({
      item: "Drought override active",
      value: s.drought_override_active ? "Yes" : "No",
      source: `${LIVE}.drought_override_active`,
    });
  }

  const caveats = [FACILITY_WIDE_CAVEAT];
  const carbonRows: ReportRow[] = [];
  if (s.carbon_data_is_real === true) {
    if (s.carbon_intensity_gco2_per_kwh !== undefined) {
      carbonRows.push({
        item: "Grid carbon intensity (gCO₂/kWh)",
        value: f(s.carbon_intensity_gco2_per_kwh, 0),
        source: `${LIVE}.carbon_intensity_gco2_per_kwh`,
      });
    }
    if (s.carbon_gco2 !== undefined) {
      carbonRows.push({
        item: "Carbon emissions, current reading (gCO₂)",
        value: f(s.carbon_gco2, 0),
        source: `${LIVE}.carbon_gco2`,
      });
    }
  } else {
    // Deliberately omitted rather than shown: a flat fallback constant would
    // read as live grid data in a document someone may forward.
    caveats.push(
      "Carbon intensity and emissions are omitted from this report: the backend reported them from a flat 475 gCO₂/kWh fallback (carbon_data_is_real is not true), not real grid data.",
    );
  }

  const sections: ReportSection[] = [
    {
      title: "Water and efficiency (latest live reading)",
      note: `Reading timestamp (simulated clock, not event time): ${s.timestamp}`,
      rows,
    },
  ];
  if (carbonRows.length > 0) sections.push({ title: "Carbon (real grid data)", rows: carbonRows });

  const seed: ProvenanceSeed = {
    usesLiveFeed: true,
    feed: feedSeedOf(s as LiveStatePayload),
    inputsFallback: s.carbon_data_is_real === true ? [] : ["carbon"],
    scenarioNote: null,
    extraRows: [],
    originSource: "WS /ws/live → origin",
  };
  return finish({ kind: "sustainability", title: "Sustainability report", sections, caveats }, seed, capture);
}

// ---------------------------------------------------------------------------
// Simulation
// ---------------------------------------------------------------------------

export interface SimulationInput {
  cfgA: SimConfig;
  cfgB: SimConfig;
  a: WhatIfResponse;
  b: WhatIfResponse;
  /** Live-feed reference (the latest simulated reading), when the feed is connected. */
  liveState: StateResponse | LiveStatePayload | null;
}

export function buildSimulationReport({ cfgA, cfgB, a, b, liveState }: SimulationInput, capture?: ReportCapture | null): Report {
  const W = "GET /api/whatif →";
  const inputRow = (label: string, va: string, vb: string) => [label, va, vb, "Simulation Lab controls (sent as /api/whatif query params)"];

  const sections: ReportSection[] = [
    {
      title: "Scenario inputs",
      note: "Inputs are the values chosen in the Simulation Lab -- they are settings, not measurements.",
      table: {
        columns: ["Parameter", "Scenario A", "Scenario B", "Source"],
        rows: [
          inputRow("Server utilisation (%)", String(cfgA.serverUtil), String(cfgB.serverUtil)),
          inputRow("Outside temp (°C)", String(cfgA.outsideTemp), String(cfgB.outsideTemp)),
          inputRow("Water stress", String(cfgA.waterStress), String(cfgB.waterStress)),
          inputRow("Chilled water setpoint (°C)", String(cfgA.chilledWaterSetpoint), String(cfgB.chilledWaterSetpoint)),
          inputRow("Cooling mode", cfgA.coolingMode, cfgB.coolingMode),
        ],
      },
    },
    {
      title: "Projected results (simulated, not measured)",
      note: `Each scenario is an isolated ${a.hours}h run on the backend digital twin at constant inputs (basis: ${a.basis}). It does not affect the live facility.`,
      table: {
        columns: ["Metric", "Scenario A", "Scenario B", "Source"],
        rows: [
          ["Mean PUE", f(a.mean_pue, 2), f(b.mean_pue, 2), `${W} mean_pue`],
          ["WUE (L/kWh)", f(a.wue, 3), f(b.wue, 3), `${W} wue`],
          ["Total water (L)", f(a.total_water_L, 0), f(b.total_water_L, 0), `${W} total_water_L`],
          ["Total energy (kWh)", f(a.total_energy_kwh, 0), f(b.total_energy_kwh, 0), `${W} total_energy_kwh`],
          ["Total CO₂ (kg)", f(a.total_co2_kg, 0), f(b.total_co2_kg, 0), `${W} total_co2_kg`],
          ["Peak outlet temp (°C)", f(a.max_outlet_temp_C, 1), f(b.max_outlet_temp_C, 1), `${W} max_outlet_temp_C`],
          ["Final cooling mode", a.final_cooling_mode, b.final_cooling_mode, `${W} final_cooling_mode`],
          ["Drought override active", a.drought_override_active ? "Yes" : "No", b.drought_override_active ? "Yes" : "No", `${W} drought_override_active`],
        ],
      },
    },
  ];

  if (liveState) {
    sections.push({
      title: "Live feed now (for reference, not part of either scenario)",
      note: `Reading timestamp (simulated clock, not event time): ${liveState.timestamp}. Origin of this reference: ${(liveState as LiveStatePayload).origin ?? "not reported by backend"}.`,
      rows: [
        { item: "PUE", value: f(liveState.pue, 2), source: `${LIVE}.pue` },
        { item: "WUE (L/kWh)", value: f(liveState.wue, 3), source: `${LIVE}.wue` },
        { item: "Server outlet temp (°C)", value: f(liveState.server_outlet_temp_C, 1), source: `${LIVE}.server_outlet_temp_C` },
      ],
    });
  }

  const caveats = [
    "Projected values come from the backend's simulation of constant inputs over the stated window; they are not forecasts of what the live facility will do.",
    FACILITY_WIDE_CAVEAT,
  ];
  if (!a.carbon_data_is_real || !b.carbon_data_is_real) caveats.push(CARBON_FALLBACK_CAVEAT);

  // The /api/whatif response carries no origin, physics version or run/scenario id: they are stated as not reported.
  const seed: ProvenanceSeed = {
    usesLiveFeed: false,
    feed: null,
    inputsFallback: !a.carbon_data_is_real || !b.carbon_data_is_real ? ["carbon"] : [],
    scenarioNote: "Scenario A and B inputs are listed in the \"Scenario inputs\" table below (preview of what these settings would produce).",
    extraRows: [{ item: "Kind", value: "Preview — what this configuration would produce (GET /api/whatif); not the live facility", source: "report endpoint class (frontend-known)" }],
    originSource: "GET /api/whatif → (no origin field)",
  };
  return finish({ kind: "simulation", title: "Simulation report", sections, caveats }, seed, capture);
}

// ---------------------------------------------------------------------------
// Incident
// ---------------------------------------------------------------------------

export function buildIncidentReport(alerts: AlertRecord[], capture?: ReportCapture | null): Report {
  const bySeverity = new Map<string, number>();
  for (const a of alerts) bySeverity.set(a.severity, (bySeverity.get(a.severity) ?? 0) + 1);
  const acknowledged = alerts.filter((a) => a.acknowledged).length;
  const inList = `in the list of ${alerts.length} fetched`;
  const NR = "not reported by backend";

  const sections: ReportSection[] = [
    {
      title: "Summary",
      note: `Counts below are tallied from the alert rows listed in this report (${inList}), not separately reported by the backend, and are not totals for all alerts.`,
      rows: [
        { item: "Alerts fetched", value: String(alerts.length), source: "GET /api/alerts (most recent first; limited request)" },
        ...[...bySeverity.entries()].map(([sev, n]) => ({
          item: `Severity ${sev} (${inList})`,
          value: String(n),
          source: "GET /api/alerts → severity (counted)",
        })),
        { item: `Acknowledged (${inList})`, value: `${acknowledged} of ${alerts.length}`, source: "GET /api/alerts → acknowledged (counted)" },
      ],
    },
    {
      title: "Alerts",
      table: {
        columns: ["ID", "Time", "Severity", "Type", "Message", "Score", "Acknowledged", "Origin", "Model version"],
        rows: alerts.map((a) => [
          String(a.id),
          a.created_at ?? "Unknown",
          a.severity,
          a.type,
          a.message,
          a.score.toFixed(4),
          a.acknowledged ? `Yes (${a.acknowledged_by ?? "unknown"})` : "No",
          a.origin ?? NR,
          a.model_version ?? NR,
        ]),
      },
      note: "Columns map directly to GET /api/alerts fields: id, created_at, severity, type, message, score, acknowledged / acknowledged_by, origin, model_version.",
    },
  ];

  const seed: ProvenanceSeed = {
    usesLiveFeed: false,
    feed: null,
    inputsFallback: [],
    scenarioNote: null,
    extraRows: [{ item: "Per-alert provenance", value: "Origin and model version are listed per alert in the Alerts table; no combined origin is computed here.", source: "GET /api/alerts → origin, model_version" }],
    originSource: "GET /api/alerts → origin (per alert; see table)",
  };
  return finish(
    {
      kind: "incident",
      title: "Incident report",
      sections,
      caveats: [
        "Alerts are facility-wide detections. The backend does not attribute an alert to a rack, and it does not store a facility-state snapshot with each alert -- so no per-alert temperatures, power draw or rack are shown, and current live readings are deliberately not substituted.",
      ],
    },
    seed,
    capture,
  );
}

// ---------------------------------------------------------------------------
// Serializers
// ---------------------------------------------------------------------------

const mdCell = (v: string) => v.replace(/\|/g, "\\|").replace(/\r?\n/g, " ");

export function reportToMarkdown(r: Report): string {
  const out: string[] = [];
  out.push(`# ${r.title}`, "", `Generated (browser time): ${r.generatedAt}`, "");
  // Stale / disconnected / not-captured is stated in the first lines.
  for (const w of r.provenance.warnings) out.push(`**Data currency — ${w}**`, "");
  for (const s of [provenanceSection(r), ...r.sections]) {
    out.push(`## ${s.title}`, "");
    if (s.note) out.push(s.note, "");
    if (s.rows) {
      out.push("| Item | Value | Source |", "| --- | --- | --- |");
      for (const row of s.rows) out.push(`| ${mdCell(row.item)} | ${mdCell(row.value)} | ${mdCell(row.source)} |`);
      out.push("");
    }
    if (s.table) {
      out.push(`| ${s.table.columns.map(mdCell).join(" | ")} |`, `| ${s.table.columns.map(() => "---").join(" | ")} |`);
      for (const row of s.table.rows) out.push(`| ${row.map(mdCell).join(" | ")} |`);
      out.push("");
    }
  }
  if (r.caveats.length > 0) {
    out.push("## Caveats", "");
    for (const c of r.caveats) out.push(`- ${c}`);
    out.push("");
  }
  return out.join("\n");
}

const esc = (v: string) =>
  v.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** Self-contained HTML (inline CSS) for print / Save-as-PDF in a new window. */
export function reportToHtml(r: Report): string {
  const parts: string[] = [];
  parts.push(`<h1>${esc(r.title)}</h1>`, `<p class="meta">Generated (browser time): ${esc(new Date(r.generatedAt).toLocaleString())}</p>`);
  for (const w of r.provenance.warnings) parts.push(`<p class="warn"><strong>Data currency — ${esc(w)}</strong></p>`);
  for (const s of [provenanceSection(r), ...r.sections]) {
    parts.push(`<h2>${esc(s.title)}</h2>`);
    if (s.note) parts.push(`<p class="note">${esc(s.note)}</p>`);
    if (s.rows) {
      parts.push("<table><thead><tr><th>Item</th><th>Value</th><th>Source</th></tr></thead><tbody>");
      for (const row of s.rows) parts.push(`<tr><td>${esc(row.item)}</td><td class="v">${esc(row.value)}</td><td class="src">${esc(row.source)}</td></tr>`);
      parts.push("</tbody></table>");
    }
    if (s.table) {
      parts.push(`<table><thead><tr>${s.table.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>`);
      for (const row of s.table.rows) parts.push(`<tr>${row.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`);
      parts.push("</tbody></table>");
    }
  }
  if (r.caveats.length > 0) {
    parts.push('<h2>Caveats</h2><ul class="caveats">', ...r.caveats.map((c) => `<li>${esc(c)}</li>`), "</ul>");
  }
  const css = `body{font:13px/1.45 system-ui,Segoe UI,Arial,sans-serif;color:#111;margin:28px}h1{font-size:20px;margin:0 0 4px}h2{font-size:14px;margin:20px 0 6px}.meta,.note{color:#555;margin:2px 0 8px}.warn{background:#fdecea;border:1px solid #d9534f;padding:6px 8px}table{border-collapse:collapse;width:100%;margin:4px 0 8px}th,td{border:1px solid #ccc;padding:4px 7px;text-align:left;vertical-align:top}th{background:#f2f2f2}.v{font-family:ui-monospace,Consolas,monospace}.src{color:#555;font-size:11px}.caveats{background:#fff7e0;border:1px solid #e6c766;padding:8px 8px 8px 26px}`;
  return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(r.title)}</title><style>${css}</style></head><body>${parts.join("")}</body></html>`;
}
