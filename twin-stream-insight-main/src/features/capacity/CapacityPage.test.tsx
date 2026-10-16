import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Capacity } from "./schema";
import type { DataState } from "@/state/dataState";
import { capacity } from "./testFixtures";

let state: DataState<Capacity>;
const refetch = vi.fn();
const useCapacity = vi.fn((..._args: unknown[]) => ({ state, refetch }));
vi.mock("./useCapacity", () => ({ useCapacity: (...a: unknown[]) => useCapacity(...a) }));
vi.mock("@/hooks/simulationContext", () => ({ useSharedSimulation: () => ({ config: { serverUtil: 65, outsideTemp: 22, coolingMode: "Auto" } }) }));

import CapacityPage from "./CapacityPage";
import { planStore } from "./planStore";

beforeEach(() => {
  planStore.reset();
  refetch.mockReset();
  useCapacity.mockClear();
  state = { status: "ready", data: capacity() };
});
afterEach(cleanup);

describe("CapacityPage", () => {
  it("shows the verdict, the estimate label and the simulated origin", () => {
    render(<CapacityPage />);
    const v = screen.getByTestId("capacity-verdict");
    expect(v).toHaveAttribute("data-verdict", "fits_with_little_margin");
    expect(v).toHaveTextContent("Fits with little margin");
    expect(v).toHaveTextContent("model-based estimate");
    expect(screen.getByTestId("capacity-label")).toHaveTextContent(/model-based estimate\. Origin: simulated/);
  });

  it("lists power, cooling and thermal rows with a glyph and a word for each status", () => {
    render(<CapacityPage />);
    const power = screen.getByTestId("capacity-row-power");
    expect(within(power).getByText("25.0 kW")).toBeInTheDocument();
    expect(power).toHaveTextContent("▲");
    expect(power).toHaveTextContent("tight");
    expect(screen.getByTestId("capacity-row-cooling")).toHaveTextContent(/●\s*ok/);
    expect(screen.getByTestId("capacity-row-thermal")).toHaveTextContent("6.7 °C");
    expect(screen.getByTestId("capacity-fit")).toHaveTextContent("by power: 13; by cooling: 19; limit: 13");
  });

  it("says 'not modelled' for a missing cooling model instead of a number", () => {
    const base = capacity().baseline;
    const none = { ...base, cooling_capacity_kw: null, cooling_headroom_kw: null, status: { ...base.status, cooling: "unknown" as const } };
    state = { status: "ready", data: capacity({ baseline: none, with_plan: none, racks_that_fit: { by_power: 13, by_cooling: null, limit: 13, note: "n" } }) };
    render(<CapacityPage />);
    expect(screen.getByTestId("capacity-row-cooling")).toHaveTextContent("not modelled");
    expect(screen.getByTestId("capacity-fit")).toHaveTextContent("by cooling: not modelled");
  });

  it("shows loading and error states instead of numbers", () => {
    state = { status: "loading" };
    const { unmount } = render(<CapacityPage />);
    expect(screen.queryByTestId("capacity-table")).toBeNull();
    unmount();
    state = { status: "error", kind: "rate_limited" };
    render(<CapacityPage />);
    expect(screen.queryByTestId("capacity-verdict")).toBeNull();
  });

  it("names an invalid field, does not clamp it, and does not change the plan", () => {
    render(<CapacityPage />);
    fireEvent.change(screen.getByLabelText("Racks to add"), { target: { value: "300" } });
    fireEvent.click(screen.getByRole("button", { name: "Evaluate" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a whole number from 0 to 200.");
    expect(screen.getByLabelText("Racks to add")).toHaveAttribute("aria-invalid", "true");
    expect(planStore.get()).toEqual({ addRacks: 10, kwPerRack: 8 });
  });

  it("applies a valid plan to the shared plan the query uses", () => {
    render(<CapacityPage />);
    fireEvent.change(screen.getByLabelText("Racks to add"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("Power per rack (kW)"), { target: { value: "12.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Evaluate" }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(planStore.get()).toEqual({ addRacks: 4, kwPerRack: 12.5 });
    expect(useCapacity.mock.calls.at(-1)?.[1]).toEqual({ addRacks: 4, kwPerRack: 12.5 });
  });

  it("states that the scenario is the current simulation settings and that added racks share the existing plant", () => {
    render(<CapacityPage />);
    expect(screen.getByTestId("capacity-scenario")).toHaveTextContent(/current simulation settings.*existing cooling plant/);
  });
});
