import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SustainabilityTab } from "./SustainabilityTab";

describe("SustainabilityTab carbon wording (T0b)", () => {
  it("labels carbon as fallback when carbon_data_is_real is false", () => {
    render(
      <SustainabilityTab
        liveState={{ carbon_intensity_gco2_per_kwh: 475, carbon_gco2: 1, carbon_data_is_real: false } as never}
        equipmentHealth={null}
      />,
    );
    expect(screen.getByText("Carbon Intensity (fallback)")).toBeTruthy();
    expect(screen.queryByText("Grid Carbon Intensity")).toBeNull();
    expect(screen.getByText(/not real grid data/i)).toBeTruthy();
  });
});
