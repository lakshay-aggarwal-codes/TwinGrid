import "@/test/resizeObserver";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { SimConfig } from "@/hooks/useSimulation";
import { ScenarioSliders } from "./ScenarioSliders";

const cfg: SimConfig = { serverUtil: 55, outsideTemp: 20, waterStress: 0.3, chilledWaterSetpoint: 7, coolingMode: "Auto", aiOptimizer: false };

describe("ScenarioSliders", () => {
  it("every slider and the mode select has an accessible name, and sliders announce their value with unit", () => {
    render(<ScenarioSliders idPrefix="t" config={cfg} onChange={() => {}} />);
    for (const name of ["Server utilisation", "Outside temperature", "Water stress index", "Chilled water setpoint"]) {
      expect(screen.getByRole("slider", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("slider", { name: "Server utilisation" })).toHaveAttribute("aria-valuetext", "55%");
    expect(screen.getByRole("slider", { name: "Outside temperature" })).toHaveAttribute("aria-valuetext", "20°C");
    expect(screen.getByRole("combobox", { name: "Cooling mode" })).toBeInTheDocument();
  });

  it("a control the view does not use says so, and the note is tied to the control", () => {
    render(<ScenarioSliders idPrefix="t" config={cfg} onChange={() => {}} notes={{ chilledWaterSetpoint: "not applied to this view" }} />);
    const note = screen.getByText("not applied to this view");
    expect(screen.getByRole("slider", { name: "Chilled water setpoint" })).toHaveAttribute("aria-describedby", note.id);
    expect(screen.getByRole("slider", { name: "Server utilisation" })).not.toHaveAttribute("aria-describedby");
  });
});
