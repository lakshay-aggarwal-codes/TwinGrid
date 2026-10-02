import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import type { AnomalyStatusPayload, LiveStatePayload, SocketStatus } from "@/api/apiClient";

const ws = vi.hoisted(() => ({
  onMessage: null as null | ((s: unknown) => unknown),
  onStatus: null as null | ((s: SocketStatus) => void),
  fetchAnomalyScore: vi.fn(),
}));

vi.mock("@/api/apiClient", () => ({
  connectWebSocket: (onMessage: (s: unknown) => unknown, onStatus?: (s: SocketStatus) => void) => {
    ws.onMessage = onMessage;
    ws.onStatus = onStatus ?? null;
    return { disconnect: vi.fn() };
  },
  fetchAnomalyScore: ws.fetchAnomalyScore,
  fetchState: vi.fn(() => new Promise(() => {})),
  fetchSimulation: vi.fn(() => new Promise(() => {})),
  fetchEquipmentHealth: vi.fn(() => new Promise(() => {})),
}));

import { SimulationProvider } from "./SimulationProvider";
import { useSharedSimulation } from "./simulationContext";

function payload(anomaly_status?: AnomalyStatusPayload): LiveStatePayload {
  return {
    timestamp: "2026-01-01T12:35:00",
    server_utilisation: 0.5,
    outside_temp_C: 22,
    server_inlet_temp_C: 20,
    server_outlet_temp_C: 30,
    it_power_kw: 300,
    cooling_power_kw: 60,
    total_power_kw: 360,
    pue: 1.2,
    water_flow_lpm: 10,
    water_consumed_L: 5,
    wue: 0.1,
    humidity_pct: 50,
    water_pressure_bar: 3,
    cooling_mode: "hybrid",
    anomaly: 0,
    interval_s: 3,
    anomaly_status,
  };
}

const status = (over: Partial<AnomalyStatusPayload> = {}): AnomalyStatusPayload => ({
  status: "ok",
  message: "No anomalies detected",
  score: 0.005,
  threshold: 0.01,
  type: "normal",
  episode: { open: false, dedupe_key: null, alert_id: null, start_seq: null, severity: null },
  ...over,
});

function Probe() {
  const { anomalyScore, anomalyStatus, latestAnomaly, events } = useSharedSimulation();
  return (
    <div>
      <div data-testid="score">{anomalyScore}</div>
      <div data-testid="status">{anomalyStatus?.status ?? "none"}</div>
      <div data-testid="latest">{latestAnomaly ? `${latestAnomaly.type}|${latestAnomaly.message}` : "none"}</div>
      <div data-testid="events">{events.map((e) => e.message).join(";")}</div>
    </div>
  );
}

const send = (p: LiveStatePayload) => act(() => void ws.onMessage?.(p));
const text = (id: string) => screen.getByTestId(id).textContent;

describe("useSimulation anomaly handling (backend T3)", () => {
  beforeEach(() => {
    ws.fetchAnomalyScore.mockReset();
    render(
      <SimulationProvider>
        <Probe />
      </SimulationProvider>
    );
  });

  it("never calls /api/anomaly_score, however many payloads arrive", () => {
    for (let i = 0; i < 30; i++) send(payload(status()));
    expect(ws.fetchAnomalyScore).not.toHaveBeenCalled();
  });

  it("exposes the server status and maps score/threshold to the 0-100 gauge (threshold = 50)", () => {
    send(payload(status({ score: 0.005, threshold: 0.01 })));
    expect(text("status")).toBe("ok");
    expect(Number(text("score"))).toBeCloseTo(25);
    send(payload(status({ status: "anomalous", score: 0.05, threshold: 0.01, type: "thermal_spike", message: "Spike" })));
    expect(Number(text("score"))).toBe(100); // clamped
  });

  it.each(["warming_up", "unavailable", "error"] as const)("%s is not shown as a normal reading", (s) => {
    send(payload(status({ status: "ok", score: 0.009 })));
    send(payload(status({ status: s, score: null, threshold: null, type: s, message: `detector ${s}` })));
    expect(text("status")).toBe(s);
    expect(Number(text("score"))).toBe(0);
  });

  it("raises one event and one latest-anomaly per episode, not per tick", () => {
    const ep = { open: true, dedupe_key: "lstm_autoencoder:v:12", alert_id: 1, start_seq: 12, severity: "CRITICAL" };
    const a = status({ status: "anomalous", score: 0.05, type: "thermal_spike", message: "Outlet temperature spike", episode: ep });
    for (let i = 0; i < 6; i++) send(payload(a));
    expect(text("events").split(";").filter((m) => m === "Outlet temperature spike")).toHaveLength(1);
    expect(text("latest")).toBe("thermal_spike|Outlet temperature spike");
    send(payload(status({ status: "anomalous", score: 0.05, type: "thermal_spike", message: "Second episode",
      episode: { ...ep, dedupe_key: "lstm_autoencoder:v:40" } })));
    expect(text("events")).toContain("Second episode");
  });

  it("reports an unavailable/error detector once per transition", () => {
    const bad = status({ status: "unavailable", score: null, threshold: null, type: "unavailable", message: "Detector down" });
    for (let i = 0; i < 5; i++) send(payload(bad));
    expect(text("events").split(";").filter((m) => m === "Detector down")).toHaveLength(1);
  });

  it("an older backend without anomaly_status leaves status null and invents nothing", () => {
    send(payload(undefined));
    expect(text("status")).toBe("none");
    expect(Number(text("score"))).toBe(0);
    expect(text("latest")).toBe("none");
  });
});
