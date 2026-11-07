import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import DatasetTelemetryPage from "./DatasetTelemetryPage";
import { fixtureSource, type DatasetTelemetrySource } from "./source";

afterEach(cleanup);

const rackText = async (rack: string) => {
  fireEvent.click(await screen.findByRole("button", { name: `Rack ${rack}` }));
  await waitFor(() => expect(screen.getByTestId("rack-readout").getAttribute("data-rack")).toBe(rack));
  return screen.getByTestId("rack-readout");
};

describe("DatasetTelemetryPage", () => {
  it("labels the data as a recorded historical dataset, separate from the simulated facility, with the fixture flagged", async () => {
    render(<DatasetTelemetryPage />);
    expect(screen.getByTestId("dataset-banner").textContent).toMatch(/Recorded dataset, source time, timezone not established/);
    expect(screen.getByTestId("dataset-banner").textContent).toMatch(/not live/);
    expect(screen.getByTestId("dataset-banner").textContent).toMatch(/36 simulated racks/);
    expect(screen.getByTestId("fixture-banner")).toBeTruthy();
    expect((await screen.findByTestId("mode-label")).textContent).toMatch(/historical\), not live/);
  });

  it("selecting different racks shows each rack's own values", async () => {
    render(<DatasetTelemetryPage />);
    const a = await screen.findByTestId("rack-readout");
    expect(a.textContent).toContain("20.12");
    expect(a.textContent).toContain("27.90");
    expect(a.textContent).not.toContain("23.47");

    const b = await rackText("2");
    expect(b.textContent).toContain("23.47");
    expect(b.textContent).not.toContain("20.12");

    const e = await rackText("5");
    expect(e.textContent).toContain("812.5");
    expect(e.textContent).not.toContain("23.47");
  });

  it("shows Not reported / No value for missing data and never falls back to another value", async () => {
    render(<DatasetTelemetryPage />);
    const b = await rackText("2");
    const rows = within(b).getAllByTestId("probe-row");
    const kinds = rows.map((r) => within(r).getByTestId("readout-value").getAttribute("data-kind"));
    expect(kinds).toEqual(["value", "missing", "absent"]);
    expect(within(rows[1]).getByTestId("readout-value").textContent).toBe("No value");
    expect(within(rows[2]).getByTestId("readout-value").textContent).toBe("Not reported");

    const e = await rackText("5");
    const eRow = within(e).getAllByTestId("probe-row")[0];
    expect(within(eRow).getByTestId("readout-value").getAttribute("data-kind")).toBe("not_reported");
    expect(within(eRow).getByTestId("readout-value").textContent).toBe("Not reported");
  });

  it("group power shows a pointer with no value; only the single-rack port shows power", async () => {
    render(<DatasetTelemetryPage />);
    const a = await screen.findByTestId("rack-readout");
    const groupPower = within(a).getByTestId("power-readout");
    expect(groupPower.getAttribute("data-power-kind")).toBe("group_pointer");
    expect(groupPower.textContent).toMatch(/racks 1, 2, 3/);
    expect(groupPower.textContent).not.toMatch(/\d+(\.\d+)? W/);

    const e = await rackText("5");
    expect(within(e).getByTestId("power-readout").getAttribute("data-power-kind")).toBe("single_rack_port");
    expect(within(e).getByTestId("power-readout").textContent).toContain("812.5 W");
  });

  it("labels provenance and quality on each reading", async () => {
    render(<DatasetTelemetryPage />);
    const b = await rackText("2");
    expect(b.textContent).toMatch(/Synthetic example · quality flagged/);
    expect(b.textContent).toMatch(/source time, timezone not established/);
  });

  it("is keyboard operable and exposes the selection state", async () => {
    render(<DatasetTelemetryPage />);
    const btn = await screen.findByRole("button", { name: "Rack 1" });
    expect(btn.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Rack 2" }).getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByRole("group", { name: "Source rack" })).toBeTruthy();
    expect(screen.getAllByRole("rowheader").length).toBeGreaterThan(0);
  });

  it("shows the attribution, modification statement and window the source supplies", async () => {
    const source: DatasetTelemetrySource = {
      ...fixtureSource,
      loadDataset: async () => ({
        rackIds: ["1"],
        attributionText: "Synthetic attribution text.",
        modificationsStatement: "Synthetic modification statement.",
        window: { first: "2000-01-01 00:00:00", last: "2000-01-02 00:00:00" },
      }),
    };
    render(<DatasetTelemetryPage source={source} />);
    expect((await screen.findByTestId("attribution")).textContent).toBe("Synthetic attribution text.");
    expect(screen.getByTestId("modifications").textContent).toBe("Synthetic modification statement.");
    expect(screen.getByTestId("dataset-window").textContent).toMatch(/2000-01-01 00:00:00 to 2000-01-02 00:00:00/);
  });

  it("reports an unknown-entity error instead of showing another rack", async () => {
    const source: DatasetTelemetrySource = { ...fixtureSource, loadDataset: async () => ({ rackIds: ["99"], attributionText: null, modificationsStatement: null, window: null }) };
    render(<DatasetTelemetryPage source={source} />);
    expect(await screen.findByText(/Rack readout unavailable: Unknown rack 99/)).toBeTruthy();
    expect(screen.queryByTestId("rack-readout")).toBeNull();
  });
});
