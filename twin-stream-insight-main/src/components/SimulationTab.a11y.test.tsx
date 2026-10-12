import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { cloneElement, type ReactElement } from "react";
import type { HourlyData, SimInputs } from "@/hooks/useSimulation";

// Same jsdom workaround as SimulationTab.test.tsx: charts need a fixed size to render.
vi.mock("recharts", async (orig) => {
  const mod = await orig<typeof import("recharts")>();
  return {
    ...mod,
    ResponsiveContainer: ({ children }: { children: ReactElement }) => (
      <div style={{ width: 800, height: 300 }}>{cloneElement(children, { width: 800, height: 300 })}</div>
    ),
  };
});

import { SimulationTab } from "./SimulationTab.tsx";

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

describe("SimulationTab charts (FE-19, Section 13 Charts)", () => {
  it("each of the three charts has a title, a 'simulated, not live' text summary and a data-table toggle", () => {
    render(<SimulationTab data={rows()} inputs={inputs} />);
    const frames = screen.getAllByTestId("chart-frame");
    expect(frames).toHaveLength(3);
    for (const f of frames) {
      expect(within(f).getByTestId("chart-summary")).toHaveTextContent("Simulated run result, not live.");
      expect(within(f).getByRole("button", { name: "View data table" })).toBeInTheDocument();
      // The chart wrapper (not recharts' own svgs) is the labelled image.
      expect(f.querySelector('[role="img"][aria-describedby]')).not.toBeNull();
    }
  });

  it("the line-chart summary states the latest step's values with units, as the backend provided them", () => {
    render(<SimulationTab data={rows()} inputs={inputs} />);
    const [line] = screen.getAllByTestId("chart-summary");
    expect(line).toHaveTextContent("3 steps, step 0 to step 2");
    expect(line).toHaveTextContent("IT power 302.0 kW");
    expect(line).toHaveTextContent("cooling power 62.0 kW");
    expect(line).toHaveTextContent("outside temperature 22.0 °C");
  });

  it("the mode chart's table and summary carry the counts that the colours encode", () => {
    render(<SimulationTab data={rows()} inputs={inputs} />);
    const summaries = screen.getAllByTestId("chart-summary");
    expect(summaries[2]).toHaveTextContent("Hybrid 2, Free Air 1");
    const frame = screen.getAllByTestId("chart-frame")[2];
    fireEvent.click(within(frame).getByRole("button", { name: "View data table" }));
    const table = within(frame).getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(3); // header + 2 modes
  });

  it("the water table names the cooling mode of every step (colour is not the only cue); an unknown mode stays unrecognised", () => {
    render(<SimulationTab data={rows(["plasma", "hybrid", "hybrid"])} inputs={inputs} />);
    const frame = screen.getAllByTestId("chart-frame")[1];
    fireEvent.click(within(frame).getByRole("button", { name: "View data table" }));
    const table = within(frame).getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(table).toHaveTextContent("Unrecognised mode");
  });
  describe("water chart: cooling mode has a non-colour cue (WCAG 1.4.1)", () => {
    // recharts animates bars in, so they are not in the DOM on the first synchronous render.
    const barFills = async (container: HTMLElement, expected: number) => {
      const sel = ".recharts-bar-rectangle path, .recharts-bar-rectangle rect";
      await waitFor(() => expect(container.querySelectorAll(sel)).toHaveLength(expected));
      return Array.from(container.querySelectorAll(sel)).map((el) => el.getAttribute("fill") ?? "");
    };

    it("every bar is filled with a pattern, never a bare colour", async () => {
      const { container } = render(<SimulationTab data={rows(["hybrid", "free_air", "plasma", "hybrid"])} inputs={inputs} />);
      const fills = await barFills(container, 4);
      for (const f of fills) expect(f).toMatch(/^url\(#[\w-]+\)$/);
    });

    it("different modes get different patterns, same mode gets the same one, and each referenced pattern exists", async () => {
      const { container } = render(<SimulationTab data={rows(["hybrid", "free_air", "plasma", "hybrid"])} inputs={inputs} />);
      const fills = await barFills(container, 4);
      expect(fills[0]).toBe(fills[3]);
      expect(new Set(fills).size).toBe(3);
      for (const f of fills) {
        const id = /^url\(#([\w-]+)\)$/.exec(f)![1];
        expect(container.querySelector(`pattern[id="${id}"]`)).not.toBeNull();
      }
    });

    it("the legend names, in text, exactly the modes present in the run", () => {
      render(<SimulationTab data={rows(["hybrid", "hybrid", "free_air"])} inputs={inputs} />);
      const legend = screen.getByTestId("mode-legend");
      const items = within(legend).getAllByRole("listitem").map((li) => li.textContent);
      expect(items).toEqual(["Free Air", "Hybrid"]);
    });

    it("an unrecognised mode is named 'Unrecognised mode' in the legend, never mapped to a known mode", () => {
      render(<SimulationTab data={rows(["plasma", "hybrid", "hybrid"])} inputs={inputs} />);
      const legend = screen.getByTestId("mode-legend");
      expect(legend).toHaveTextContent("Unrecognised mode");
      expect(legend).toHaveTextContent("Hybrid");
    });

    it("two mounted tabs never share pattern ids", () => {
      const a = render(<SimulationTab data={rows()} inputs={inputs} />);
      const b = render(<SimulationTab data={rows()} inputs={inputs} />);
      const ids = (c: HTMLElement) => Array.from(c.querySelectorAll("pattern")).map((p) => p.id);
      const shared = ids(a.container).filter((id) => ids(b.container).includes(id));
      expect(shared).toEqual([]);
    });
  });
});
