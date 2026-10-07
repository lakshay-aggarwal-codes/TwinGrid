import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { DataState } from "@/state/dataState";
import type { PreviewKpi } from "@/hooks/useSimulation";

// The anomaly components are covered by FE-07's tests; here they are only neighbours.
vi.mock("./AnomalyAlert", () => ({ AnomalyAlert: () => <div data-testid="anomaly-alert" /> }));
vi.mock("./AnomalyGauge", () => ({ AnomalyGauge: () => <div data-testid="anomaly-gauge" /> }));

import { LiveMonitor } from "./LiveMonitor";

const preview = (over: Partial<PreviewKpi["value"]> = {}): PreviewKpi => ({
  value: { pue: 1.2345, wue: 0.4567, itPowerKw: 300.4, coolingPowerKw: 60.2, outletTempC: 31.37, waterFlowLpm: 12.5, ...over },
  provenance: { kind: "preview", inputs: { utilisationPct: 65, outsideTempC: 22, waterStress: 0.4, coolingMode: "Auto" } },
});
const ready = (data = preview(), extra: Partial<Extract<DataState<PreviewKpi>, { status: "ready" }>> = {}): DataState<PreviewKpi> => ({
  status: "ready",
  data,
  ...extra,
});

const mount = (state: DataState<PreviewKpi>, onRetry = vi.fn()) =>
  render(<LiveMonitor previewKpi={state} onRetryPreview={onRetry} events={[]} />);

describe("LiveMonitor preview KPIs (FE-08)", () => {
  it("loading: no KPI values at all (never 0), an explicit loading state", () => {
    const { container } = mount({ status: "loading" });
    expect(container.querySelectorAll("[data-kpi-field]")).toHaveLength(0);
    expect(screen.getByTestId("preview-kpis").textContent).not.toMatch(/\b0\b/);
    expect(container.querySelector("[data-state='loading']")).not.toBeNull();
    expect(screen.queryByTestId("preview-inputs")).toBeNull();
  });

  it("error: an explicit error state with a retry; no KPI values", () => {
    const retry = vi.fn();
    const { container } = mount({ status: "error", kind: "network" }, retry);
    expect(container.querySelectorAll("[data-kpi-field]")).toHaveLength(0);
    expect(container.querySelector("[data-state='error']")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("ready: labelled Preview, shows the inputs, and is not styled or worded as live", () => {
    const { container } = mount(ready());
    const block = screen.getByTestId("preview-kpis");
    expect(block.querySelector("[data-flag='preview']")).not.toBeNull();
    expect(block).toHaveTextContent(/Preview — what this configuration would produce/);
    expect(screen.getByTestId("preview-inputs")).toHaveTextContent(
      "At utilisation 65 %, outside 22 °C, water stress 0.4, cooling mode Auto."
    );
    expect(block).toHaveTextContent(/not the live feed/i);
    expect(container.querySelector("[data-freshness='live']")).toBeNull();
    expect(block.className).toMatch(/border-dashed/);
  });

  it("ready: values are the backend's, formatted to the unit-table precision", () => {
    mount(ready());
    const get = (f: string) => document.querySelector(`[data-kpi-field='${f}']`)!.textContent!;
    expect(get("pue")).toContain("1.23");
    expect(get("wue")).toContain("0.46");
    expect(get("wue")).toContain("L/kWh");
    expect(get("it_power_kw")).toContain("300.4");
    expect(get("water_flow_lpm")).toContain("12.5");
    expect(get("water_flow_lpm")).toContain("L/min");
  });

  it("the client-derived 'Water / Hour' tile and trend arrows are gone", () => {
    const { container } = mount(ready());
    expect(screen.queryByText(/Water \/ Hour/i)).toBeNull();
    expect(container.querySelectorAll("[data-kpi-field]")).toHaveLength(6);
    expect(container.querySelector("svg.lucide-trending-up, svg.lucide-trending-down, svg.lucide-minus")).toBeNull();
  });

  it("failed refresh: last good values stay, labelled stale, still carrying their own inputs", () => {
    const { container } = mount(ready(preview(), { freshness: "stale", refreshFailed: true }));
    expect(container.querySelectorAll("[data-kpi-field]")).toHaveLength(6);
    expect(screen.getByTestId("preview-inputs")).toHaveTextContent("utilisation 65 %");
    expect(container.querySelector("[data-state='stale']")).not.toBeNull();
  });

  it("has no spatial/floor heat map elements", () => {
    const { container } = mount(ready());
    expect(screen.queryByText(/floor/i)).toBeNull();
    expect(container.querySelector("canvas, [data-heatmap], [data-testid*='heatmap']")).toBeNull();
  });

  it("event times are labelled as browser receipt time, not data time", () => {
    mount(ready());
    expect(screen.getByTestId("event-times-note")).toHaveTextContent(/browser receipt times, not data times/i);
  });
});
