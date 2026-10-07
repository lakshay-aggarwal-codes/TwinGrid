import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import type { SocketStatus } from "@/api/apiClient";
import { ApiError } from "@/api/apiError";

const api = vi.hoisted(() => ({
  fetchState: vi.fn(),
  fetchSimulation: vi.fn(),
}));

vi.mock("@/api/apiClient", () => ({
  connectWebSocket: (_m: unknown, _s?: (s: SocketStatus) => void) => ({ disconnect: vi.fn() }),
  fetchAnomalyScore: vi.fn(),
  fetchState: api.fetchState,
  fetchSimulation: api.fetchSimulation,
}));

import { SimulationProvider } from "./SimulationProvider";
import { useSharedSimulation } from "./simulationContext";

const backendState = (over: Record<string, unknown> = {}) => ({
  timestamp: "2026-01-01T12:35:00",
  server_utilisation: 0.65,
  outside_temp_C: 22,
  server_inlet_temp_C: 20,
  server_outlet_temp_C: 31.37,
  it_power_kw: 300.4,
  cooling_power_kw: 60.2,
  total_power_kw: 360.6,
  pue: 1.2345,
  water_flow_lpm: 12.5,
  water_consumed_L: 5,
  wue: 0.4567,
  humidity_pct: 50,
  water_pressure_bar: 3,
  cooling_mode: "hybrid",
  anomaly: 0,
  ...over,
});

function Probe() {
  const s = useSharedSimulation();
  return (
    <div>
      <div data-testid="kpi">{JSON.stringify(s.previewKpi)}</div>
      <div data-testid="hourly">{JSON.stringify(s.hourlyData)}</div>
      <div data-testid="sim-inputs">{JSON.stringify(s.simInputs)}</div>
      <div data-testid="sim-error">{String(s.simError)}</div>
      <button onClick={() => s.setConfig({ ...s.config, serverUtil: 80 })}>util80</button>
      <button onClick={s.runSimulation}>run</button>
      <button onClick={s.retryPreview}>retry</button>
    </div>
  );
}

const kpi = () => JSON.parse(screen.getByTestId("kpi").textContent!);
const flush = () => act(async () => { await vi.advanceTimersByTimeAsync(350); });

beforeEach(() => {
  vi.useFakeTimers();
  api.fetchState.mockReset();
  api.fetchSimulation.mockReset();
});
afterEach(() => vi.useRealTimers());

const mount = () => render(<SimulationProvider><Probe /></SimulationProvider>);

describe("useSimulation preview KPI (FE-08)", () => {
  it("before the first response there is no value at all: loading, never zeros", async () => {
    api.fetchState.mockReturnValue(new Promise(() => {}));
    mount();
    expect(kpi()).toEqual({ status: "loading" });
    await flush();
    expect(kpi()).toEqual({ status: "loading" });
  });

  it("ready: backend values unrounded and uncomputed, with the inputs they answer for", async () => {
    api.fetchState.mockResolvedValue(backendState());
    mount();
    await flush();
    const k = kpi();
    expect(k.status).toBe("ready");
    expect(k.data.value).toEqual({
      pue: 1.2345,
      wue: 0.4567,
      itPowerKw: 300.4,
      coolingPowerKw: 60.2,
      outletTempC: 31.37,
      waterFlowLpm: 12.5,
    });
    expect(k.data.provenance).toEqual({
      kind: "preview",
      inputs: { utilisationPct: 65, outsideTempC: 22, waterStress: 0.4, coolingMode: "Auto" },
    });
    // no client derivation: water/hour (wue x it_power) and a trend are gone
    expect(Object.keys(k.data.value)).not.toContain("waterPerHour");
    expect(Object.keys(k.data.value)).not.toContain("pueTrend");
    const [params, signal] = api.fetchState.mock.calls[0];
    expect(params).toEqual({ utilisation: 0.65, outside_temp: 22, water_stress: 0.4, mode: "auto" });
    expect(signal).toBeInstanceOf(AbortSignal);
  });

  it("first request fails: an explicit error state (kind only), not zeros", async () => {
    api.fetchState.mockRejectedValue(new ApiError({ kind: "network" }));
    mount();
    await flush();
    expect(kpi()).toMatchObject({ status: "error", kind: "network" });
  });

  it("later request fails: the last good preview stays, labelled stale, with ITS OWN inputs (not the new slider value)", async () => {
    api.fetchState.mockResolvedValueOnce(backendState());
    mount();
    await flush();
    api.fetchState.mockRejectedValueOnce(new ApiError({ kind: "server", status: 500 }));
    fireEvent.click(screen.getByText("util80"));
    await flush();
    const k = kpi();
    expect(k).toMatchObject({ status: "ready", refreshFailed: true, freshness: "stale" });
    expect(k.data.provenance.inputs.utilisationPct).toBe(65);
    expect(k.data.value.pue).toBe(1.2345);
  });

  it("only the four /api/state inputs trigger a request (the chilled-water setpoint does not)", async () => {
    api.fetchState.mockResolvedValue(backendState());
    mount();
    await flush();
    expect(api.fetchState).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText("util80"));
    await flush();
    expect(api.fetchState).toHaveBeenCalledTimes(2);
  });

  it("retry goes back to loading and requests again", async () => {
    api.fetchState.mockRejectedValueOnce(new ApiError({ kind: "network" }));
    mount();
    await flush();
    api.fetchState.mockResolvedValueOnce(backendState());
    fireEvent.click(screen.getByText("retry"));
    expect(kpi()).toEqual({ status: "loading" });
    await flush();
    expect(kpi().status).toBe("ready");
  });
});

describe("useSimulation run mapping (FE-08)", () => {
  beforeEach(() => {
    api.fetchState.mockReturnValue(new Promise(() => {}));
  });

  it("maps one backend field per column: no derived water, unknown cooling mode stays unknown, step is an index", async () => {
    api.fetchSimulation.mockResolvedValue([
      backendState({ cooling_mode: "plasma", water_consumed_L: 7, pue: 1.3 }),
      backendState({ cooling_mode: "free_air", water_consumed_L: 9, pue: 1.1 }),
    ]);
    mount();
    fireEvent.click(screen.getByText("run"));
    await flush();
    const rows = JSON.parse(screen.getByTestId("hourly").textContent!);
    expect(rows).toEqual([
      { step: 0, itPowerKw: 300.4, coolingPowerKw: 60.2, outsideTempC: 22, waterConsumedL: 7, pue: 1.3, coolingMode: "plasma" },
      { step: 1, itPowerKw: 300.4, coolingPowerKw: 60.2, outsideTempC: 22, waterConsumedL: 9, pue: 1.1, coolingMode: "free_air" },
    ]);
    expect(JSON.parse(screen.getByTestId("sim-inputs").textContent!)).toEqual({
      hours: 24,
      meanUtilisationPct: 65,
      meanOutsideTempC: 22,
      waterStress: 0.4,
    });
    expect(screen.getByTestId("sim-error").textContent).toBe("false");
  });

  it("a failed run is an explicit error flag, not an empty success", async () => {
    api.fetchSimulation.mockRejectedValue(new ApiError({ kind: "server", status: 500 }));
    mount();
    fireEvent.click(screen.getByText("run"));
    await flush();
    expect(screen.getByTestId("sim-error").textContent).toBe("true");
    expect(screen.getByTestId("hourly").textContent).toBe("[]");
  });
});
