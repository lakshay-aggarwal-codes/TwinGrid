import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LiveStatePayload } from "@/api/models";

const { downloadExport } = vi.hoisted(() => ({ downloadExport: vi.fn() }));
vi.mock("./exportTable", async (orig) => ({ ...(await orig<typeof import("./exportTable")>()), downloadExport }));

const state: LiveStatePayload = {
  timestamp: "2026-01-01T00:05:00", server_utilisation: 0.5, outside_temp_C: 20, server_inlet_temp_C: 24, server_outlet_temp_C: 35,
  it_power_kw: 100, cooling_power_kw: 25, total_power_kw: 125, pue: 1.25, water_flow_lpm: 60, water_consumed_L: 1234, wue: 0.456,
  humidity_pct: 40, water_pressure_bar: 2, cooling_mode: "chiller", anomaly: 0,
  carbon_intensity_gco2_per_kwh: 475, carbon_gco2: 100, carbon_data_is_real: false, origin: "simulated",
};
let view: { frame: { value: LiveStatePayload } | null; freshness: { state: string; ageMs: number | null } };
vi.mock("@/telemetry/useFeed", () => ({ useFeed: (sel: (v: unknown) => unknown) => sel(view) }));

import { ExportButtons } from "./ExportButtons";
import ReportPage from "./ReportPage";

beforeEach(() => {
  downloadExport.mockReset();
  view = { frame: { value: state }, freshness: { state: "live", ageMs: 0 } };
});

describe("ExportButtons", () => {
  const cols = [{ key: "a", header: "a", value: (r: { a: string }) => r.a }];
  it("downloads CSV and JSON with UTC-stamped names", () => {
    render(<ExportButtons label="alerts" columns={cols} rows={[{ a: "x" }]} now={() => new Date(Date.UTC(2026, 9, 16, 3, 15, 7))} />);
    fireEvent.click(screen.getByRole("button", { name: "Export alerts as CSV" }));
    fireEvent.click(screen.getByRole("button", { name: "Export alerts as JSON" }));
    expect(downloadExport.mock.calls[0][0]).toBe("twingrid-alerts-20261016T031507Z.csv");
    expect(downloadExport.mock.calls[0][1]).toBe("a\r\nx\r\n");
    expect(downloadExport.mock.calls[1][0]).toBe("twingrid-alerts-20261016T031507Z.json");
    expect(JSON.parse(downloadExport.mock.calls[1][1]).origin).toBe("simulated");
    expect(screen.getByRole("status").textContent).toMatch(/JSON downloaded: 1 row\./);
  });
  it("is disabled with a reason when there are no rows", () => {
    render(<ExportButtons label="alerts" columns={cols} rows={[]} />);
    const b = screen.getByRole("button", { name: "Export alerts as CSV" });
    expect(b).toBeDisabled();
    expect(b).toHaveAttribute("title", expect.stringMatching(/Nothing to export/));
  });
  it("offers only the requested formats", () => {
    render(<ExportButtons label="x" columns={cols} rows={[{ a: "1" }]} formats={["json"]} />);
    expect(screen.queryByRole("button", { name: /CSV/ })).toBeNull();
    expect(screen.getByRole("button", { name: /JSON/ })).toBeEnabled();
  });
});

describe("ReportPage", () => {
  const open = () => render(<MemoryRouter><ReportPage /></MemoryRouter>);
  it("shows the carbon fallback label, the claim boundary and the provenance block", () => {
    open();
    expect(screen.getByTestId("report-carbon-label").textContent).toMatch(/ASSUMPTION/);
    expect(screen.getByTestId("report-claim-boundary").textContent).toMatch(/not an audited/);
    expect(screen.getByTestId("report-provenance").textContent).toMatch(/Simulated data/);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/executive \/ ESG summary/);
  });
  it("has a print button that calls window.print and a report export", () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    open();
    fireEvent.click(screen.getByRole("button", { name: /Print/ }));
    expect(print).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Export report as CSV" }));
    expect(String(downloadExport.mock.calls[0][1])).toMatch(/^section,item,value,unit,source_field\r\n/);
    print.mockRestore();
  });
  it("shows an empty state, not zeros, when no frame has arrived", () => {
    view = { frame: null, freshness: { state: "connecting", ageMs: null } };
    open();
    expect(screen.getByTestId("report-empty")).toBeInTheDocument();
    expect(screen.queryByText("PUE")).toBeNull();
    expect(screen.getByRole("button", { name: "Export report as CSV" })).toBeDisabled();
  });
  it("shows a stale banner above the data", () => {
    view = { frame: { value: state }, freshness: { state: "stale", ageMs: 45000 } };
    open();
    expect(screen.getByTestId("report-banner").textContent).toMatch(/^STALE/);
  });
});
