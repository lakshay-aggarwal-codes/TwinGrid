import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SustainabilityTab } from "./SustainabilityTab";
import { feedIn } from "@/three/feedTestUtils";

const carbon = (real: boolean | undefined) => ({ carbon_intensity_gco2_per_kwh: 475, carbon_gco2: 1, carbon_data_is_real: real, water_stress: 0.4 });

describe("SustainabilityTab carbon wording (T0b)", () => {
  it("labels carbon as fallback when carbon_data_is_real is false", () => {
    render(<SustainabilityTab feed={feedIn("live", { state: carbon(false) })} equipmentHealth={null} />);
    expect(screen.getByText("Carbon Intensity (fallback)")).toBeTruthy();
    expect(screen.queryByText("Grid Carbon Intensity")).toBeNull();
    expect(screen.getByText(/not real grid data/i)).toBeTruthy();
  });
});

describe("SustainabilityTab freshness (FE-06)", () => {
  it("live: current values with the origin + freshness badge on each card", () => {
    const { container } = render(<SustainabilityTab feed={feedIn("live", { state: carbon(true) })} equipmentHealth={null} />);
    expect(container.firstElementChild).toHaveAttribute("data-readout", "current");
    expect(screen.getByText("40%")).toBeTruthy();
    expect(container.querySelectorAll("[data-freshness='live']")).toHaveLength(2);
    expect(container.querySelectorAll("[data-origin='simulated']")).toHaveLength(2);
    expect(screen.queryAllByTestId("last-known")).toHaveLength(0);
  });

  it.each(["stale", "disconnected", "reconnecting"] as const)("%s: values are last known with their age, never presented as live", (state) => {
    const { container } = render(<SustainabilityTab feed={feedIn(state, { state: carbon(false) })} equipmentHealth={null} />);
    expect(container.firstElementChild).toHaveAttribute("data-readout", "last-known");
    expect(screen.getAllByTestId("last-known")).toHaveLength(2);
    for (const el of screen.getAllByTestId("last-known")) expect(el).toHaveTextContent("Last known · 42 s ago");
    expect(screen.queryByText(/^Live facility reading/)).toBeNull();
    expect(screen.getByText(/Last known facility reading/)).toBeTruthy();
    expect(container.querySelector("[data-freshness='live']")).toBeNull();
  });

  it.each(["connecting", "unavailable"] as const)("%s: no numbers, a state notice on each card", (state) => {
    const { container } = render(<SustainabilityTab feed={feedIn(state, { state: carbon(false) })} equipmentHealth={null} />);
    expect(container.firstElementChild).toHaveAttribute("data-readout", "none");
    expect(screen.queryByText("40%")).toBeNull();
    expect(screen.queryByText("475")).toBeNull();
    expect(container.querySelectorAll("[data-state]").length).toBeGreaterThanOrEqual(2);
  });

  it("a field the backend did not send reads 'not reported', not 0 and not hidden", () => {
    render(<SustainabilityTab feed={feedIn("live", { state: { carbon_data_is_real: undefined } })} equipmentHealth={null} />);
    expect(screen.getByText(/Carbon intensity not reported/)).toBeTruthy();
    expect(screen.getByText(/Water stress not reported/)).toBeTruthy();
  });
});
