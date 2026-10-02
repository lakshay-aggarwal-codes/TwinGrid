import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import type { LiveStatePayload } from "@/api/apiClient";
import type { LivenessStatus } from "@/hooks/liveness.ts";

// Navigation chrome is not under test here.
vi.mock("@/components/transition/RotateLink", () => ({
  RotateLink: ({ to, children }: { to: string; children: ReactNode }) => <a href={to}>{children}</a>,
}));
vi.mock("@/pages/lazyPages.ts", () => ({ loadAnalyticsPage: () => Promise.resolve({}) }));

import { TwinHeader } from "./TwinHeader";
import { SimulationContext, type SimulationValue } from "@/hooks/simulationContext";

function state(extra: Partial<LiveStatePayload> = {}): LiveStatePayload {
  return {
    timestamp: "2026-01-01T12:35:00",
    server_utilisation: 0.5,
    outside_temp_C: 22,
    server_inlet_temp_C: 20,
    server_outlet_temp_C: 30,
    it_power_kw: 300,
    cooling_power_kw: 60,
    total_power_kw: 360,
    pue: 1.23,
    water_flow_lpm: 10,
    water_consumed_L: 5,
    wue: 0.456,
    humidity_pct: 50,
    water_pressure_bar: 3,
    cooling_mode: "hybrid",
    anomaly: 0,
    ...extra,
  };
}

function renderHeader(liveness: LivenessStatus, liveState: LiveStatePayload | null) {
  const value = { liveness } as unknown as SimulationValue;
  return render(
    <MemoryRouter>
      <SimulationContext.Provider value={value}>
        <TwinHeader
          onOpenSearch={() => {}}
          liveState={liveState}
          mode="physical"
          onModeChange={() => {}}
          simulationOpen={false}
          onToggleSimulation={() => {}}
          operationsOpen={false}
          onToggleOperations={() => {}}
          incidentsOpen={false}
          onToggleIncidents={() => {}}
        />
      </SimulationContext.Provider>
    </MemoryRouter>
  );
}

const status = () => screen.getByTestId("liveness");

describe("TwinHeader liveness + origin (T1a)", () => {
  it("shows Live only when the feed is live", () => {
    renderHeader("live", state({ origin: "simulated" }));
    expect(status()).toHaveTextContent("Live");
    expect(status()).toHaveAttribute("data-liveness", "live");
  });

  it.each([
    ["stale", "Stale"],
    ["disconnected", "Disconnected"],
    ["connecting", "Connecting"],
  ] as const)("shows %s instead of Live", (liveness, label) => {
    renderHeader(liveness, state({ origin: "simulated" }));
    expect(status()).toHaveTextContent(label);
    expect(status()).not.toHaveTextContent(/^live$/i);
  });

  it("keeps the last readings visible but dims them when stale or disconnected", () => {
    const { unmount } = renderHeader("disconnected", state({ origin: "simulated" }));
    expect(screen.getByText("1.23")).toBeInTheDocument();
    expect(screen.getByTestId("live-readings").className).toContain("opacity-50");
    unmount();
    renderHeader("live", state({ origin: "simulated" }));
    expect(screen.getByTestId("live-readings").className).not.toContain("opacity-50");
  });

  it("renders the data-driven Simulated banner for origin=simulated", () => {
    renderHeader("live", state({ origin: "simulated" }));
    const banner = screen.getByTestId("origin-banner");
    expect(banner).toHaveTextContent("Simulated");
    expect(banner).toHaveAttribute("data-origin-tone", "simulated");
    expect(banner.getAttribute("title")).toMatch(/not event time/i);
  });

  it("shows 'Unverified source' when the payload has no origin", () => {
    renderHeader("live", state());
    const banner = screen.getByTestId("origin-banner");
    expect(banner).toHaveTextContent("Unverified source");
    expect(banner).toHaveAttribute("data-origin-tone", "unverified");
  });

  it("shows no origin banner and placeholder readings before any payload", () => {
    renderHeader("connecting", null);
    expect(screen.queryByTestId("origin-banner")).toBeNull();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });
});
