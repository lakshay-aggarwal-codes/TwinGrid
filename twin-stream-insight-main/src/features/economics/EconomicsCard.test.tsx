import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Economics } from "./schema";
import type { DataState } from "@/state/dataState";

const cost = (total: number) => ({ energy_kwh: 2400, peak_kwh: 500, off_peak_kwh: 1900, energy_cost: total - 40, peak_kw: 100, demand_cost: 40, total_cost: total });
const data = (saving: number): Economics => ({
  label: "illustrative tariff, not a quote", estimate_label: "model estimate on simulated data", origin: "simulated", basis: "BASIS TEXT",
  currency: "USD", currency_note: "Rates are taken to be in this currency. Nothing is converted.", is_default_tariff: true,
  scenario: { inputs: {}, mean_pue: 1.3, cost: cost(282 - saving) }, baseline: { inputs: {}, mean_pue: 1.3, cost: cost(282) },
  savings: { energy_cost: saving, demand_cost: 0, total_cost: saving, total_pct: saving === 0 ? 0 : (saving / 282) * 100 }, carbon_data_is_real: false,
});
let state: DataState<Economics>;
const refetch = vi.fn();
vi.mock("./useEconomics", () => ({ useEconomics: () => ({ state, refetch }) }));
vi.mock("@/hooks/simulationContext", () => ({ useSharedSimulation: () => ({ config: {} }) }));

import EconomicsCard from "./EconomicsCard";

beforeEach(() => {
  window.localStorage.clear();
  refetch.mockReset();
  state = { status: "ready", data: data(28.2) };
});

describe("EconomicsCard", () => {
  it("shows the cost, the illustrative label and a worded saving", () => {
    render(<EconomicsCard />);
    expect(screen.getByTestId("economics-total")).toHaveTextContent("$253.80");
    expect(screen.getByTestId("economics-label")).toHaveTextContent("illustrative tariff, not a quote");
    expect(screen.getByTestId("economics-label")).toHaveTextContent("model estimate on simulated data");
    expect(screen.getByTestId("economics-savings")).toHaveTextContent(/^Saves \$28\.20 per day vs baseline/);
    expect(screen.getByText(/flat fallback intensity/)).toBeInTheDocument();
  });
  it("words a worse scenario as costing more, and an equal one as the same", () => {
    state = { status: "ready", data: data(-10) };
    const { unmount } = render(<EconomicsCard />);
    expect(screen.getByTestId("economics-savings")).toHaveTextContent(/^Costs \$10\.00 more/);
    unmount();
    state = { status: "ready", data: data(0) };
    render(<EconomicsCard />);
    expect(screen.getByTestId("economics-savings")).toHaveTextContent("Same cost as the baseline");
  });
  it("shows loading and error states instead of numbers", () => {
    state = { status: "loading" };
    const { unmount } = render(<EconomicsCard />);
    expect(screen.queryByTestId("economics-total")).toBeNull();
    unmount();
    state = { status: "error", kind: "rate_limited" };
    render(<EconomicsCard />);
    expect(screen.queryByTestId("economics-total")).toBeNull();
  });
  it("opens the tariff drawer, rejects a bad value by name and keeps a good one in this browser", async () => {
    render(<EconomicsCard />);
    fireEvent.click(screen.getByRole("button", { name: /Tariff settings/ }));
    const peak = await screen.findByLabelText(/Peak energy rate/);
    fireEvent.change(peak, { target: { value: "abc" } });
    fireEvent.click(screen.getByRole("button", { name: "Save tariff" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Peak|Enter a number/);
    expect(peak).toHaveAttribute("aria-invalid", "true");
    fireEvent.change(peak, { target: { value: "0.25" } });
    fireEvent.click(screen.getByRole("button", { name: "Save tariff" }));
    await waitFor(() => expect(JSON.parse(window.localStorage.getItem("twingrid.economics.tariff.v1") ?? "{}").peakRate).toBe(0.25));
  });
});
