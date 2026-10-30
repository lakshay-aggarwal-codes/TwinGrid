import "@/test/resizeObserver";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

let role: string | null = "viewer";
vi.mock("@/hooks/useAuth.ts", async () => {
  const real = await vi.importActual<typeof import("@/hooks/useAuth.ts")>("@/hooks/useAuth");
  return { ...real, useRole: () => real.roleView(role) };
});

import { DashboardSidebar } from "./DashboardSidebar";
import type { SimConfig } from "@/hooks/useSimulation";

const cfg: SimConfig = { serverUtil: 55, outsideTemp: 20, waterStress: 0.3, chilledWaterSetpoint: 7, coolingMode: "Auto", aiOptimizer: false };
const SLIDERS = ["Server Utilisation", "Outside Temperature", "Water Stress Index", "Chilled Water Setpoint"];

const renderSidebar = (r: string | null) => {
  role = r;
  const onChange = vi.fn();
  const onRunSim = vi.fn();
  render(
    <MemoryRouter>
      <DashboardSidebar config={cfg} onChange={onChange} onRunSim={onRunSim} simRunning={false} collapsed={false} onToggle={vi.fn()} />
    </MemoryRouter>,
  );
  return { onChange, onRunSim };
};

describe("DashboardSidebar is read-only for viewers", () => {
  it("a viewer: all four sliders, the cooling mode and Run 24h Simulation are locked, with the reason in text", () => {
    const { onRunSim } = renderSidebar("viewer");
    for (const name of SLIDERS) {
      expect(screen.getByRole("slider", { name })).toHaveAttribute("aria-disabled", "true");
    }
    expect(screen.getByRole("combobox", { name: "Cooling mode" })).toBeDisabled();
    const run = screen.getByRole("button", { name: /Run 24h Simulation/ });
    expect(run).toBeDisabled();
    expect(run).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByTestId("controls-locked-note")).toHaveTextContent("Requires operator role");
    fireEvent.click(run);
    expect(onRunSim).not.toHaveBeenCalled();
  });

  it("a viewer still sees the current values", () => {
    renderSidebar("viewer");
    expect(screen.getByText("55%")).toBeInTheDocument();
    expect(screen.getByText("20°C")).toBeInTheDocument();
  });

  it.each(["operator", "admin"])("%s: every control is enabled and no lock note is shown", (r) => {
    const { onRunSim } = renderSidebar(r);
    for (const name of SLIDERS) {
      expect(screen.getByRole("slider", { name })).not.toHaveAttribute("aria-disabled", "true");
    }
    expect(screen.getByRole("combobox", { name: "Cooling mode" })).toBeEnabled();
    const run = screen.getByRole("button", { name: /Run 24h Simulation/ });
    expect(run).toBeEnabled();
    expect(screen.queryByTestId("controls-locked-note")).toBeNull();
    fireEvent.click(run);
    expect(onRunSim).toHaveBeenCalledTimes(1);
  });

  it("the collapse toggle stays usable for a viewer", () => {
    renderSidebar("viewer");
    expect(screen.getByRole("button", { name: "Collapse controls sidebar" })).toBeEnabled();
  });
});
