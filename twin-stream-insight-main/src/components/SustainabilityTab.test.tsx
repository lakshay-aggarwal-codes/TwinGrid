import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SustainabilityTab } from "./SustainabilityTab";
import { feedIn } from "@/three/feedTestUtils";
import type { DataState } from "@/state/dataState";
import type { EquipmentHealthResponse } from "@/api/apiClient";

const LOADING: DataState<EquipmentHealthResponse> = { status: "loading" };
const ready = (data: EquipmentHealthResponse): DataState<EquipmentHealthResponse> => ({ status: "ready", data });

const carbon = (real: boolean | undefined) => ({ carbon_intensity_gco2_per_kwh: 475, carbon_gco2: 1, carbon_data_is_real: real, water_stress: 0.4 });

describe("SustainabilityTab carbon wording (T0b)", () => {
  it("labels carbon as fallback when carbon_data_is_real is false", () => {
    render(<SustainabilityTab feed={feedIn("live", { state: carbon(false) })} equipmentHealth={LOADING} />);
    expect(screen.getByText("Carbon Intensity (fallback)")).toBeTruthy();
    expect(screen.queryByText("Grid Carbon Intensity")).toBeNull();
    expect(screen.getByText(/not real grid data/i)).toBeTruthy();
  });
});

describe("SustainabilityTab freshness (FE-06)", () => {
  it("live: current values with the origin + freshness badge on each card", () => {
    const { container } = render(<SustainabilityTab feed={feedIn("live", { state: carbon(true) })} equipmentHealth={LOADING} />);
    expect(container.firstElementChild).toHaveAttribute("data-readout", "current");
    expect(screen.getByText("40%")).toBeTruthy();
    expect(container.querySelectorAll("[data-freshness='live']")).toHaveLength(2);
    expect(container.querySelectorAll("[data-origin='simulated']")).toHaveLength(2);
    expect(screen.queryAllByTestId("last-known")).toHaveLength(0);
  });

  it.each(["stale", "disconnected", "reconnecting"] as const)("%s: values are last known with their age, never presented as live", (state) => {
    const { container } = render(<SustainabilityTab feed={feedIn(state, { state: carbon(false) })} equipmentHealth={LOADING} />);
    expect(container.firstElementChild).toHaveAttribute("data-readout", "last-known");
    expect(screen.getAllByTestId("last-known")).toHaveLength(2);
    for (const el of screen.getAllByTestId("last-known")) expect(el).toHaveTextContent("Last known · 42 s ago");
    expect(screen.queryByText(/^Live facility reading/)).toBeNull();
    expect(screen.getByText(/Last known facility reading/)).toBeTruthy();
    expect(container.querySelector("[data-freshness='live']")).toBeNull();
  });

  it.each(["connecting", "unavailable"] as const)("%s: no numbers, a state notice on each card", (state) => {
    const { container } = render(<SustainabilityTab feed={feedIn(state, { state: carbon(false) })} equipmentHealth={LOADING} />);
    expect(container.firstElementChild).toHaveAttribute("data-readout", "none");
    expect(screen.queryByText("40%")).toBeNull();
    expect(screen.queryByText("475")).toBeNull();
    expect(container.querySelectorAll("[data-state]").length).toBeGreaterThanOrEqual(2);
  });

  it("a field the backend did not send reads 'not reported', not 0 and not hidden", () => {
    render(<SustainabilityTab feed={feedIn("live", { state: { carbon_data_is_real: undefined } })} equipmentHealth={LOADING} />);
    expect(screen.getByText(/Carbon intensity not reported/)).toBeTruthy();
    expect(screen.getByText(/Water stress not reported/)).toBeTruthy();
  });
});

describe("SustainabilityTab equipment health (FE-08)", () => {
  const live = () => feedIn("live", { state: carbon(true) });
  const full: EquipmentHealthResponse = {
    available: true,
    lstm: { mae: 12.34, rmse: 15, r2: 0.8 },
    baseline: { mae: 20.5, rmse: 25, r2: 0.5 },
    mae_improvement_pct: 39.8,
    dataset_caveat: "Trained on a proxy dataset.",
  };

  it("is named 'Equipment health (proxy model)', never 'Predictive Maintenance'", () => {
    render(<SustainabilityTab feed={live()} equipmentHealth={ready(full)} />);
    expect(screen.getByText("Equipment health (proxy model)")).toBeTruthy();
    expect(screen.queryByText(/Predictive Maintenance/i)).toBeNull();
  });

  it("loading: an explicit loading state, not a missing card", () => {
    render(<SustainabilityTab feed={live()} equipmentHealth={LOADING} />);
    expect(screen.getByTestId("equipment-health")).toBeTruthy();
    expect(screen.getByText(/Loading equipment-health results/)).toBeTruthy();
  });

  it("request failure: an explicit error state inside the card", () => {
    render(<SustainabilityTab feed={live()} equipmentHealth={{ status: "error", kind: "network" }} />);
    const card = screen.getByTestId("equipment-health");
    expect(card.querySelector("[data-state]")).not.toBeNull();
    expect(card.textContent).not.toMatch(/MAE/);
  });

  it("backend says available:false: an explicit unavailable state with fixed copy (backend message is not rendered)", () => {
    render(
      <SustainabilityTab
        feed={live()}
        equipmentHealth={ready({ available: false, message: "Run `python -m src.predictive_maintenance.train` first." })}
      />
    );
    expect(screen.getByText(/No equipment-health model results are available/)).toBeTruthy();
    expect(screen.queryByText(/python -m/)).toBeNull();
  });

  it("available: the caveat leads, metrics follow, the headline percentage is last and small", () => {
    render(<SustainabilityTab feed={live()} equipmentHealth={ready(full)} />);
    const card = screen.getByTestId("equipment-health");
    const caveat = screen.getByTestId("equipment-caveat");
    const improvement = screen.getByTestId("equipment-improvement");
    expect(caveat).toHaveTextContent("Proxy model");
    expect(caveat).toHaveTextContent("Trained on a proxy dataset.");
    expect(card.textContent).toContain("12.34");
    expect(card.textContent).toContain("20.50");
    expect(improvement).toHaveTextContent("MAE improvement over baseline: 39.8%");
    // document order: caveat, then metrics, then the improvement line
    expect(caveat.compareDocumentPosition(improvement) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(card.querySelector("dl")!.compareDocumentPosition(improvement) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(improvement.className).toMatch(/text-xs/);
  });

  it("missing fields read 'not reported', not 0; a missing caveat is stated", () => {
    render(<SustainabilityTab feed={live()} equipmentHealth={ready({ available: true })} />);
    const card = screen.getByTestId("equipment-health");
    expect(card.textContent).toMatch(/LSTM MAE\s*not reported/);
    expect(screen.getByTestId("equipment-improvement")).toHaveTextContent("not reported");
    expect(screen.getByText(/Dataset caveat: not reported/)).toBeTruthy();
  });

  it("wears the provenance badge (REST payload with no origin: Unverified source)", () => {
    render(<SustainabilityTab feed={live()} equipmentHealth={ready(full)} />);
    expect(screen.getByTestId("equipment-health").querySelector("[data-origin='unverified']")).not.toBeNull();
  });
});
