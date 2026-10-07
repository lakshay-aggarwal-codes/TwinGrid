import { describe, it, expect, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import type { LiveStatePayload, SocketStatus } from "@/api/apiClient.ts";

const ws = vi.hoisted(() => ({
  onMessage: null as null | ((s: unknown) => unknown),
  onStatus: null as null | ((s: SocketStatus) => void),
}));

vi.mock("@/api/apiClient", () => ({
  connectWebSocket: (onMessage: (s: unknown) => unknown, onStatus?: (s: SocketStatus) => void) => {
    ws.onMessage = onMessage;
    ws.onStatus = onStatus ?? null;
    return { disconnect: vi.fn() };
  },
  fetchState: vi.fn(() => new Promise(() => {})),
  fetchSimulation: vi.fn(() => new Promise(() => {})),
  fetchEquipmentHealth: vi.fn(() => new Promise(() => {})),
}));

import { SimulationProvider } from "./SimulationProvider";
import { useFeed } from "@/telemetry/useFeed";
import { liveFrame } from "@/telemetry/testUtils";

function Probe() {
  const stamped = useFeed((v) => v.frame);
  return (
    <div data-testid="p">
      {stamped ? `${stamped.value.pue}|${stamped.freshness.state}|${stamped.provenance.origin ?? "unverified"}` : "none"}
    </div>
  );
}

describe("SimulationProvider + feed store", () => {
  it("provides the feed to descendants as stamped data", () => {
    render(
      <SimulationProvider>
        <Probe />
      </SimulationProvider>
    );
    expect(screen.getByTestId("p")).toHaveTextContent("none");
    act(() => ws.onStatus?.("open"));
    act(() => void ws.onMessage?.(liveFrame({ pue: 1.3, origin: "simulated" } as Partial<LiveStatePayload>)));
    expect(screen.getByTestId("p")).toHaveTextContent("1.3|live|simulated");
  });
});
