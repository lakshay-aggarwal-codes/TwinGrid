import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CarbonSchedule } from "./schema";
import type { DataState } from "@/state/dataState";
import { flat, synthetic, unverified, varying } from "./testData";

let state: DataState<CarbonSchedule>;
const refetch = vi.fn();
const useCarbonSchedule = vi.fn((..._args: unknown[]) => ({ state, refetch }));
vi.mock("./useCarbonSchedule", () => ({ useCarbonSchedule: (...a: unknown[]) => useCarbonSchedule(...a) }));

import CarbonScheduleCard from "./CarbonScheduleCard";

type Call = [{ durationH: number; loadKw: number; synthetic: boolean }, boolean];
const lastCall = () => useCarbonSchedule.mock.calls[useCarbonSchedule.mock.calls.length - 1] as unknown as Call;

beforeEach(() => {
  useCarbonSchedule.mockClear();
  refetch.mockReset();
  state = { status: "ready", data: varying() };
});

describe("CarbonScheduleCard with a varying series", () => {
  it("shows the best window, its numbers, a worded saving, the strip and the honesty label", () => {
    render(<CarbonScheduleCard />);
    expect(screen.getByRole("heading", { level: 2, name: /Carbon-aware scheduling/ })).toBeInTheDocument();
    expect(screen.getByTestId("carbon-headline")).toHaveAttribute("data-status", "ok");
    expect(screen.getByTestId("carbon-headline")).toHaveTextContent("Lowest-carbon 4-hour window: 00:00 to 04:00");
    const w = screen.getByTestId("carbon-window");
    expect(w).toHaveTextContent("00:00 to 04:00");
    expect(w).toHaveTextContent("302 gCO₂/kWh");
    expect(w).toHaveTextContent("120.6 kg CO₂");
    expect(screen.getByTestId("carbon-saving")).toHaveTextContent("Saves 4.0 kg CO₂ (3.2 %) vs the average start time.");
    expect(screen.getByTestId("hour-strip")).toHaveAccessibleName(/lowest 300 gCO₂\/kWh at 00:00.*Best window 00:00 to 04:00, outlined/);
    expect(screen.getByTestId("hour-strip").querySelectorAll("[data-best]")).toHaveLength(4);
    expect(screen.getByTestId("carbon-label")).toHaveTextContent("hour-of-day pattern, not a forecast");
    expect(screen.getByTestId("carbon-label")).toHaveTextContent("The load is hypothetical");
    expect(screen.getByText(/Average intensity is not marginal intensity/)).toBeInTheDocument();
    expect(screen.queryByTestId("carbon-synthetic-banner")).toBeNull();
  });

  it("starts with 4 h and 100 kW, real data (not the demonstration) and a request", () => {
    render(<CarbonScheduleCard />);
    expect(lastCall()).toEqual([{ durationH: 4, loadKw: 100, synthetic: false }, true]);
  });
});

describe("CarbonScheduleCard with the flat fallback", () => {
  beforeEach(() => {
    state = { status: "ready", data: flat() };
  });
  it("says there is no carbon variation and shows no window, no saving and no strip", () => {
    render(<CarbonScheduleCard />);
    expect(screen.getByTestId("carbon-headline")).toHaveTextContent("No carbon variation in current data");
    expect(screen.getByTestId("carbon-headline")).toHaveAttribute("data-status", "no_variation");
    expect(screen.getByTestId("carbon-message")).toHaveTextContent("no saving is claimed");
    expect(screen.getByTestId("carbon-flat-value")).toHaveTextContent("Every hour: 475 gCO₂/kWh");
    expect(screen.queryByTestId("carbon-window")).toBeNull();
    expect(screen.queryByTestId("carbon-saving")).toBeNull();
    expect(screen.queryByTestId("hour-strip")).toBeNull();
    expect(screen.queryByText(/Saves/)).toBeNull();
    expect(screen.getByTestId("carbon-label")).toHaveTextContent("the signal is an assumption");
  });
  it("offers the synthetic demonstration as an explicit, labelled choice, off by default", () => {
    render(<CarbonScheduleCard />);
    const box = screen.getByRole("checkbox", { name: /synthetic demonstration profile/i });
    expect(box).not.toBeChecked();
    expect(screen.getByText(/made-up curve for illustration, not grid data/)).toBeInTheDocument();
    fireEvent.click(box);
    expect(lastCall()[0].synthetic).toBe(true);
  });
});

describe("CarbonScheduleCard other states", () => {
  it("unverified data gets a message and no window or saving", () => {
    state = { status: "ready", data: unverified() };
    render(<CarbonScheduleCard />);
    expect(screen.getByTestId("carbon-headline")).toHaveAttribute("data-status", "unverified");
    expect(screen.getByTestId("carbon-message")).toHaveTextContent("no window and no saving is suggested");
    expect(screen.queryByTestId("carbon-window")).toBeNull();
    expect(screen.queryByTestId("carbon-saving")).toBeNull();
  });

  it("the synthetic profile carries a loud label, a dashed strip and a demonstration headline", () => {
    state = { status: "ready", data: synthetic() };
    render(<CarbonScheduleCard />);
    expect(screen.getByTestId("carbon-synthetic-banner")).toHaveTextContent("SYNTHETIC DEMONSTRATION profile, not grid data");
    expect(screen.getByTestId("carbon-headline")).toHaveTextContent(/^Demonstration only:/);
    expect(screen.getByTestId("hour-strip")).toHaveAttribute("data-synthetic", "true");
    expect(screen.getByText(/Synthetic profile: not grid data, not a forecast/)).toBeInTheDocument();
  });

  it("refuses invalid entries with an alert and makes no request for them", () => {
    render(<CarbonScheduleCard />);
    fireEvent.change(screen.getByLabelText(/Run length/), { target: { value: "0" } });
    expect(screen.getByRole("alert")).toHaveTextContent("1 to 24");
    expect(screen.getByLabelText(/Run length/)).toHaveAttribute("aria-invalid", "true");
    expect(lastCall()[1]).toBe(false);
    expect(screen.getByTestId("carbon-invalid")).toBeInTheDocument();
    expect(screen.queryByTestId("carbon-headline")).toBeNull();
    fireEvent.change(screen.getByLabelText(/Run length/), { target: { value: "6" } });
    fireEvent.change(screen.getByLabelText(/Flexible load/), { target: { value: "-2" } });
    expect(screen.getByRole("alert")).toHaveTextContent("greater than 0");
    expect(lastCall()[1]).toBe(false);
  });

  it("shows loading and error states instead of numbers", () => {
    state = { status: "loading" };
    const { unmount } = render(<CarbonScheduleCard />);
    expect(screen.queryByTestId("carbon-headline")).toBeNull();
    unmount();
    state = { status: "error", kind: "rate_limited" };
    render(<CarbonScheduleCard />);
    expect(screen.queryByTestId("carbon-headline")).toBeNull();
    expect(screen.queryByTestId("carbon-window")).toBeNull();
  });
});
