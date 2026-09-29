import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { useState } from "react";

const connectWebSocket = vi.fn(() => ({ disconnect: vi.fn() }));

vi.mock("@/api/apiClient", () => ({
  connectWebSocket: (...args: unknown[]) => connectWebSocket(...(args as [])),
  fetchState: vi.fn(() => new Promise(() => {})),
  fetchSimulation: vi.fn(() => new Promise(() => {})),
  fetchAnomalyScore: vi.fn(() => new Promise(() => {})),
  fetchEquipmentHealth: vi.fn(() => new Promise(() => {})),
}));

import { SimulationProvider } from "./SimulationProvider";
import { useSharedSimulation } from "./simulationContext";

function Page({ name }: { name: string }) {
  const { config } = useSharedSimulation();
  return <div data-testid={name}>{config.serverUtil}</div>;
}

function Harness() {
  const [page, setPage] = useState<"a" | "b">("a");
  return (
    <SimulationProvider>
      <button onClick={() => setPage((p) => (p === "a" ? "b" : "a"))}>swap</button>
      <Page name={page} />
    </SimulationProvider>
  );
}

describe("SimulationProvider", () => {
  beforeEach(() => connectWebSocket.mockClear());

  it("opens exactly one WebSocket however many times the page swaps", () => {
    render(<Harness />);
    const swap = screen.getByText("swap");
    for (let i = 0; i < 10; i++) fireEvent.click(swap);
    // 10 swaps => back on page "a"; proves the swaps really re-rendered.
    expect(screen.getByTestId("a")).toBeTruthy();
    expect(connectWebSocket).toHaveBeenCalledTimes(1);
  });

  it("throws a clear error when used outside the provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Page name="x" />)).toThrow(/SimulationProvider/);
    spy.mockRestore();
  });
});
