import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Capacity } from "./schema";
import type { DataState } from "@/state/dataState";
import { headroomOverlay } from "@/three/headroomOverlay";
import { capacity } from "./testFixtures";

let state: DataState<Capacity>;
const useCapacity = vi.fn((..._args: unknown[]) => ({ state, refetch: vi.fn() }));
vi.mock("./useCapacity", () => ({ useCapacity: (...a: unknown[]) => useCapacity(...a) }));
vi.mock("@/hooks/simulationContext", () => ({ useSharedSimulation: () => ({ config: {} }) }));

import OverlayControl from "./OverlayControl";
import feature from "./index";
import { planStore } from "./planStore";

const mount = () =>
  render(
    <MemoryRouter>
      <OverlayControl context={{}} />
    </MemoryRouter>,
  );

beforeEach(() => {
  headroomOverlay.reset();
  planStore.reset();
  useCapacity.mockClear();
  state = { status: "ready", data: capacity() };
});
afterEach(cleanup);

describe("headroom overlay toggle", () => {
  it("is off by default: nothing is requested and nothing is published", () => {
    mount();
    expect(screen.getByTestId("headroom-toggle")).toHaveAttribute("aria-pressed", "false");
    expect(useCapacity.mock.calls.every((c) => c[2] === false)).toBe(true); // `enabled` is false: no request
    expect(headroomOverlay.getState()).toEqual({ enabled: false, status: null, powerKw: null, coolingKw: null });
    expect(screen.queryByTestId("headroom-legend")).toBeNull();
  });

  it("turns on: pressed, legend with glyphs, the scene gets the plan's status and facility totals", () => {
    mount();
    fireEvent.click(screen.getByTestId("headroom-toggle"));
    expect(screen.getByTestId("headroom-toggle")).toHaveAttribute("aria-pressed", "true");
    expect(useCapacity.mock.calls.at(-1)?.[2]).toBe(true);
    expect(headroomOverlay.getState()).toEqual({ enabled: true, status: "tight", powerKw: 25, coolingKw: 75 });
    const legend = screen.getByTestId("headroom-legend");
    expect(legend).toHaveTextContent("●");
    expect(legend).toHaveTextContent("▲");
    expect(legend).toHaveTextContent("■");
    expect(legend).toHaveTextContent("model-based estimate on simulated data");
    expect(legend).toHaveTextContent("even share per zone");
    expect(legend.querySelector('[data-active="true"]')).toHaveTextContent("tight");
    expect(screen.getByTestId("headroom-summary")).toHaveTextContent("+10 racks at 8 kW: tight.");
  });

  it("turns off again: the scene's overlay state is cleared", () => {
    mount();
    fireEvent.click(screen.getByTestId("headroom-toggle"));
    fireEvent.click(screen.getByTestId("headroom-toggle"));
    expect(screen.getByTestId("headroom-toggle")).toHaveAttribute("aria-pressed", "false");
    expect(headroomOverlay.getState()).toMatchObject({ enabled: false, status: null });
  });

  it("while loading or failed it publishes no status (nothing is drawn from a missing result)", () => {
    state = { status: "loading" };
    const first = mount();
    fireEvent.click(screen.getByTestId("headroom-toggle"));
    expect(headroomOverlay.getState()).toMatchObject({ enabled: true, status: null });
    first.unmount();
    state = { status: "error", kind: "rate_limited" };
    mount();
    fireEvent.click(screen.getByTestId("headroom-toggle"));
    expect(headroomOverlay.getState()).toMatchObject({ enabled: true, status: null });
  });

  it("leaving the page switches the overlay off", () => {
    const { unmount } = mount();
    fireEvent.click(screen.getByTestId("headroom-toggle"));
    unmount();
    expect(headroomOverlay.getState().enabled).toBe(false);
  });

  it("is registered in the facility-inspector slot, and the feature has the /capacity route", () => {
    expect(feature.slots?.map((s) => s.slot)).toEqual(["facility-inspector"]);
    expect(feature.route?.path).toBe("/capacity");
    expect(feature.nav?.label).toBe("Capacity");
  });
});
