import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { cloneElement, type ReactElement } from "react";
import type { HourlyData, SimInputs } from "@/hooks/useSimulation";

// jsdom has no layout: give charts a fixed size so axis labels and legends actually render.
vi.mock("recharts", async (orig) => {
  const mod = await orig<typeof import("recharts")>();
  return {
    ...mod,
    ResponsiveContainer: ({ children }: { children: ReactElement }) => (
      <div style={{ width: 800, height: 300 }}>{cloneElement(children, { width: 800, height: 300 })}</div>
    ),
  };
});

import { SimulationTab } from "./SimulationTab";

const rows = (modes: string[] = ["hybrid", "hybrid", "free_air"]): HourlyData[] =>
  modes.map((coolingMode, step) => ({
    step,
    itPowerKw: 300 + step,
    coolingPowerKw: 60 + step,
    outsideTempC: 20 + step,
    waterConsumedL: 5 + step,
    pue: [1.2, 1.3, 1.4][step % 3],
    coolingMode,
  }));
const inputs: SimInputs = { hours: 24, meanUtilisationPct: 65, meanOutsideTempC: 22, waterStress: 0.4 };

describe("SimulationTab (FE-08)", () => {
  it("renders only tiles whose value is a backend field (or a labelled mean of one)", () => {
    const { container } = render(<SimulationTab data={rows()} inputs={inputs} />);
    const tiles = [...container.querySelectorAll("[data-tile]")].map((t) => ({
      label: t.getAttribute("data-tile"),
      source: t.getAttribute("data-source-field"),
    }));
    expect(tiles).toEqual([{ label: "Mean PUE", source: "pue" }]);
  });

  it("Mean PUE is the mean of the backend's hourly pue, over the rows actually returned, and says so", () => {
    render(<SimulationTab data={rows()} inputs={inputs} />);
    const tile = document.querySelector("[data-tile='Mean PUE']")!;
    expect(tile).toHaveTextContent("1.30"); // (1.2 + 1.3 + 1.4) / 3, not / 24
    expect(tile).toHaveTextContent("mean of hourly backend PUE (display aggregation)");
  });

  it("the fabricated tiles are gone: Water Saved, CO₂ Avoided, Total Energy, 'vs baseline'", () => {
    const { container } = render(<SimulationTab data={rows()} inputs={inputs} />);
    // Tiles only: the "not provided" note below them names what is missing, by design.
    const tileText = [...container.querySelectorAll("[data-tile]")].map((t) => t.textContent).join(" ");
    for (const re of [/Water Saved/i, /CO₂ Avoided/i, /CO2 Avoided/i, /Total Energy/i]) expect(tileText).not.toMatch(re);
    for (const re of [/Water Saved/i, /CO₂ Avoided/i, /CO2 Avoided/i, /vs baseline/i, /MWh/]) {
      expect(container.textContent).not.toMatch(re);
    }
  });

  it("states what the backend does not provide, instead of inventing it", () => {
    render(<SimulationTab data={rows()} inputs={inputs} />);
    expect(screen.getByTestId("sim-not-provided")).toHaveTextContent(/Not provided by the backend/);
    expect(screen.getByTestId("sim-not-provided")).toHaveTextContent(/total energy, total water, CO₂/);
  });

  it("shows the inputs the run was requested with, as means, beside the results", () => {
    render(<SimulationTab data={rows()} inputs={inputs} />);
    expect(screen.getByTestId("run-inputs")).toHaveTextContent(
      "Simulated run of 3 steps (requested 24 h): mean utilisation 65 %, mean outside 22 °C, water stress 0.4."
    );
    expect(document.querySelector("[data-provenance-strip]")).not.toBeNull();
  });

  it("the X axis is labelled as steps from the start of the run, not clock hours", () => {
    const { container } = render(<SimulationTab data={rows()} inputs={inputs} />);
    expect(container.textContent).toContain("step (hours from start of simulated run)");
    expect(container.textContent).not.toMatch(/\d{1,2}:00/); // no "0:00", "1:00" clock ticks
  });

  it("water is the backend field as reported, titled as such", () => {
    render(<SimulationTab data={rows()} inputs={inputs} />);
    expect(screen.getByText(/Water consumed \(L\) — as reported per step/)).toBeTruthy();
    expect(screen.getByText(/not summed or derived here/)).toBeTruthy();
    expect(screen.queryByText(/Water Consumption by Hour/i)).toBeNull();
  });

  it("an unrecognised cooling mode stays unrecognised; it is not turned into Auto", () => {
    const { container } = render(<SimulationTab data={rows(["plasma", "hybrid", "hybrid"])} inputs={inputs} />);
    expect(container.textContent).toContain("Unrecognised mode");
    expect(container.textContent).not.toMatch(/\bAuto\b/);
  });

  it("no results yet: the prompt, no tiles", () => {
    const { container } = render(<SimulationTab data={[]} inputs={null} />);
    expect(screen.getByText(/Run a simulation from the sidebar/)).toBeTruthy();
    expect(container.querySelectorAll("[data-tile]")).toHaveLength(0);
  });

  it("a failed run is an explicit error, with or without earlier results", () => {
    const empty = render(<SimulationTab data={[]} inputs={null} failed />);
    expect(empty.container.querySelector("[data-state='error']")).not.toBeNull();
    empty.unmount();
    const withData = render(<SimulationTab data={rows()} inputs={inputs} failed />);
    expect(withData.container.querySelector("[data-state='error']")).not.toBeNull();
  });
});
