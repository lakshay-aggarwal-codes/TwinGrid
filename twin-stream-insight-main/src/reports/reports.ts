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
  OptimizeSummary,
  StateResponse,
  WhatIfResponse,
} from "@/api/apiClient";
import type { LatestAnomaly, SimConfig } from "@/hooks/useSimulation";

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

export interface Report {
  kind: ReportKind;
  title: string;
  /** ISO timestamp of when this report was generated (client clock). */
  generatedAt: string;
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
// Operational
// ---------------------------------------------------------------------------

export interface OperationalInput {
  liveState: StateResponse;
  /** The 0-100 gauge value from useSimulation: clamp(score ÷ threshold × 50). */
  anomalyGauge: number;
  latestAnomaly: LatestAnomaly | null;
  /** Most recent PPO evaluation run from the Operations Console this session. */
  optimizeSummary: OptimizeSummary | null;
}

export function buildOperationalReport(input: OperationalInput): Report {
  const { liveState: s, anomalyGauge, latestAnomaly, optimizeSummary } = input;

  const sections: ReportSection[] = [
    {
      title: "Facility state (latest live reading)",
      note: `Reading timestamp reported by the backend: ${s.timestamp}`,
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
    {
      title: "Anomaly detector",
      rows: [
        {
          item: "Gauge value (0–100; 50 = alert threshold)",
          value: f(anomalyGauge, 0),
          source: "GET /api/anomaly_score → clamp(score ÷ threshold × 50, 0, 100), computed in hooks/useSimulation.ts",
        },
        {
          item: "Most recent alert this session",
          value: latestAnomaly ? `${latestAnomaly.type} — ${latestAnomaly.message}` : "None received",
          source: "GET /api/anomaly_score → type, message",
        },
      ],
    },
  ];

  if (optimizeSummary) {
    const o = optimizeSummary;
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

  return {
    kind: "operational",
    title: "Operational report",
    generatedAt: new Date().toISOString(),
    sections,
    caveats,
  };
}

// ---------------------------------------------------------------------------
// Sustainability
// ---------------------------------------------------------------------------

export function buildSustainabilityReport(s: StateResponse): Report {
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
      note: `Reading timestamp reported by the backend: ${s.timestamp}`,
      rows,
    },
  ];
  if (carbonRows.length > 0) sections.push({ title: "Carbon (real grid data)", rows: carbonRows });

  return {
    kind: "sustainability",
    title: "Sustainability report",
    generatedAt: new Date().toISOString(),
    sections,
    caveats,
  };
}

// ---------------------------------------------------------------------------
// Simulation
// ---------------------------------------------------------------------------

export interface SimulationInput {
  cfgA: SimConfig;
  cfgB: SimConfig;
  a: WhatIfResponse;
  b: WhatIfResponse;
  /** Measured-now reference, when the live feed is connected. */
  liveState: StateResponse | null;
}

export function buildSimulationReport({ cfgA, cfgB, a, b, liveState }: SimulationInput): Report {
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
      title: "Measured now (for reference, not part of either scenario)",
      note: `Reading timestamp reported by the backend: ${liveState.timestamp}`,
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

  return {
    kind: "simulation",
    title: "Simulation report",
    generatedAt: new Date().toISOString(),
    sections,
    caveats,
  };
}

// ---------------------------------------------------------------------------
// Incident
// ---------------------------------------------------------------------------

export function buildIncidentReport(alerts: AlertRecord[]): Report {
  const bySeverity = new Map<string, number>();
  for (const a of alerts) bySeverity.set(a.severity, (bySeverity.get(a.severity) ?? 0) + 1);
  const acknowledged = alerts.filter((a) => a.acknowledged).length;

  const sections: ReportSection[] = [
    {
      title: "Summary",
      note: "Counts below are tallied from the alert rows listed in this report (derived), not separately reported by the backend.",
      rows: [
        { item: "Alerts included", value: String(alerts.length), source: "GET /api/alerts (most recent 50, newest first)" },
        ...[...bySeverity.entries()].map(([sev, n]) => ({
          item: `Severity ${sev}`,
          value: String(n),
          source: "GET /api/alerts → severity (counted)",
        })),
        { item: "Acknowledged", value: `${acknowledged} of ${alerts.length}`, source: "GET /api/alerts → acknowledged (counted)" },
      ],
    },
    {
      title: "Alerts",
      table: {
        columns: ["ID", "Time", "Severity", "Type", "Message", "Score", "Acknowledged"],
        rows: alerts.map((a) => [
          String(a.id),
          a.created_at ?? "Unknown",
          a.severity,
          a.type,
          a.message,
          a.score.toFixed(4),
          a.acknowledged ? `Yes (${a.acknowledged_by ?? "unknown"})` : "No",
        ]),
      },
      note: "Columns map directly to GET /api/alerts fields: id, created_at, severity, type, message, score, acknowledged / acknowledged_by.",
    },
  ];

  return {
    kind: "incident",
    title: "Incident report",
    generatedAt: new Date().toISOString(),
    sections,
    caveats: [
      "Alerts are facility-wide detections. The backend does not attribute an alert to a rack, and it does not store a facility-state snapshot with each alert -- so no per-alert temperatures, power draw or rack are shown, and current live readings are deliberately not substituted.",
    ],
  };
}

// ---------------------------------------------------------------------------
// Serializers
// ---------------------------------------------------------------------------

const mdCell = (v: string) => v.replace(/\|/g, "\\|").replace(/\r?\n/g, " ");

export function reportToMarkdown(r: Report): string {
  const out: string[] = [];
  out.push(`# ${r.title}`, "", `Generated: ${new Date(r.generatedAt).toLocaleString()} (${r.generatedAt})`, "");
  for (const s of r.sections) {
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
  parts.push(`<h1>${esc(r.title)}</h1>`, `<p class="meta">Generated: ${esc(new Date(r.generatedAt).toLocaleString())}</p>`);
  for (const s of r.sections) {
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
  const css = `body{font:13px/1.45 system-ui,Segoe UI,Arial,sans-serif;color:#111;margin:28px}h1{font-size:20px;margin:0 0 4px}h2{font-size:14px;margin:20px 0 6px}.meta,.note{color:#555;margin:2px 0 8px}table{border-collapse:collapse;width:100%;margin:4px 0 8px}th,td{border:1px solid #ccc;padding:4px 7px;text-align:left;vertical-align:top}th{background:#f2f2f2}.v{font-family:ui-monospace,Consolas,monospace}.src{color:#555;font-size:11px}.caveats{background:#fff7e0;border:1px solid #e6c766;padding:8px 8px 8px 26px}`;
  return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(r.title)}</title><style>${css}</style></head><body>${parts.join("")}</body></html>`;
}
