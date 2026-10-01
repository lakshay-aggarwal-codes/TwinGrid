import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { TwinHeader } from "./TwinHeader";

// Navigation/transition internals are irrelevant to this copy test.
vi.mock("@/components/transition/RotateLink", () => ({
  RotateLink: ({ children }: { children: React.ReactNode }) => <a href="/analytics">{children}</a>,
}));

describe("TwinHeader (T0b temporary banner)", () => {
  it("always shows the simulated / no-measured-telemetry banner", () => {
    render(
      <MemoryRouter>
        <TwinHeader
          onOpenSearch={() => {}}
          liveState={null}
          mode="physical"
          onModeChange={() => {}}
          simulationOpen={false}
          onToggleSimulation={() => {}}
          operationsOpen={false}
          onToggleOperations={() => {}}
          incidentsOpen={false}
          onToggleIncidents={() => {}}
        />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("simulated-banner").textContent).toBe("SIMULATED — no measured telemetry");
  });
});
