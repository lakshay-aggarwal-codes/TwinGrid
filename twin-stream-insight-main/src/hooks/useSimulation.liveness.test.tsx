import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import type { LiveStatePayload, SocketStatus } from "@/api/apiClient";

const ws = vi.hoisted(() => ({
  onMessage: null as null | ((s: unknown) => unknown),
  onStatus: null as null | ((s: SocketStatus) => void),
  connects: 0,
}));

vi.mock("@/api/apiClient", () => ({
  connectWebSocket: (onMessage: (s: unknown) => unknown, onStatus?: (s: SocketStatus) => void) => {
    ws.onMessage = onMessage;
    ws.onStatus = onStatus ?? null;
    ws.connects += 1;
    return { disconnect: vi.fn() };
  },
  fetchState: vi.fn(() => new Promise(() => {})),
  fetchSimulation: vi.fn(() => new Promise(() => {})),
  fetchAnomalyScore: vi.fn(() => new Promise(() => {})),
  fetchEquipmentHealth: vi.fn(() => new Promise(() => {})),
}));

import { SimulationProvider } from "./SimulationProvider";
import { useSharedSimulation } from "./simulationContext";

function payload(extra: Partial<LiveStatePayload> = {}): LiveStatePayload {
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
    ...extra,
  };
}

function Probe() {
  const { liveness } = useSharedSimulation();
  return <div data-testid="liveness">{liveness}</div>;
}

const shown = () => screen.getByTestId("liveness").textContent;
const send = (p: LiveStatePayload) => act(() => void ws.onMessage?.(p));
const socket = (s: SocketStatus) => act(() => ws.onStatus?.(s));
const advance = (ms: number) => act(() => void vi.advanceTimersByTime(ms));

describe("useSimulation liveness (T1a)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    ws.onMessage = null;
    ws.onStatus = null;
    ws.connects = 0;
    render(
      <SimulationProvider>
        <Probe />
      </SimulationProvider>
    );
  });
  afterEach(() => vi.useRealTimers());

  it("starts as connecting and stays a single socket", () => {
    expect(shown()).toBe("connecting");
    expect(ws.connects).toBe(1);
  });

  it("is live after a payload on an open socket", () => {
    socket("open");
    send(payload({ interval_s: 3 }));
    expect(shown()).toBe("live");
  });

  it("leaves Live immediately when the socket closes", () => {
    socket("open");
    send(payload({ interval_s: 3 }));
    expect(shown()).toBe("live");
    socket("closed");
    expect(shown()).toBe("disconnected");
  });

  it("goes stale within the stale window when the socket stays open but payloads stop", () => {
    socket("open");
    send(payload({ interval_s: 3 })); // window = 3 * 3 s = 9 s
    advance(8_000);
    expect(shown()).toBe("live");
    advance(2_000);
    expect(shown()).toBe("stale");
  });

  it("recovers to live when payloads resume, and keeps working across a reconnect", () => {
    socket("open");
    send(payload({ interval_s: 3 }));
    socket("closed");
    socket("connecting");
    expect(shown()).toBe("disconnected");
    socket("open");
    send(payload({ interval_s: 3 }));
    expect(shown()).toBe("live");
  });

  it("uses the default window when an older backend sends no interval_s", () => {
    socket("open");
    send(payload());
    advance(8_000);
    expect(shown()).toBe("live");
    advance(2_000);
    expect(shown()).toBe("stale");
  });

  it("is not fooled by the payload's own timestamps (sim_time / ts_ingest are not liveness)", () => {
    socket("open");
    send(payload({ interval_s: 3, sim_time: "2000-01-01T00:00:00", ts_ingest: "2000-01-01T00:00:00+00:00" }));
    expect(shown()).toBe("live");
  });
});
