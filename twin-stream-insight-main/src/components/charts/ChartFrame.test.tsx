import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { ChartFrame } from "./ChartFrame.tsx";

const columns = [
  { key: "step", header: "Step" },
  { key: "kw", header: "IT power (kW)" },
];
const rows = [
  { step: 0, kw: "300.0" },
  { step: 1, kw: "301.0" },
];

function setup() {
  return render(
    <ChartFrame title="Power by step" summary="Simulated run result, not live. 2 steps." columns={columns} rows={rows}>
      <svg data-testid="plot" />
    </ChartFrame>
  );
}

describe("ChartFrame (FE-19, Section 13 Charts)", () => {
  it("has a visible title, and the chart is an image named by it and described by the summary", () => {
    setup();
    expect(screen.getByRole("heading", { name: "Power by step" })).toBeVisible();
    const img = screen.getByRole("img", { name: "Power by step" });
    const summary = screen.getByTestId("chart-summary");
    expect(img.getAttribute("aria-describedby")).toBe(summary.id);
    expect(summary).toHaveTextContent("Simulated run result, not live. 2 steps.");
    expect(within(img).getByTestId("plot")).toBeInTheDocument();
  });

  it("the data table is hidden until requested, then shows exactly the rows, with row headers and a caption", () => {
    setup();
    const toggle = screen.getByRole("button", { name: "View data table" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("table")).toBeNull();

    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Hide data table" })).toHaveAttribute("aria-expanded", "true");
    const table = screen.getByRole("table", { name: "Data behind the chart: Power by step" });
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Step", "IT power (kW)"]);
    const body = within(table).getAllByRole("row").slice(1);
    expect(body).toHaveLength(2);
    expect(within(body[1]).getByRole("rowheader")).toHaveTextContent("1");
    expect(within(body[1]).getByRole("cell")).toHaveTextContent("301.0");
  });

  it("the toggle controls the table region", () => {
    setup();
    const toggle = screen.getByRole("button", { name: "View data table" });
    const target = document.getElementById(toggle.getAttribute("aria-controls") ?? "");
    expect(target).not.toBeNull();
    expect(target).not.toBeVisible();
    fireEvent.click(toggle);
    expect(target).toBeVisible();
  });
});
