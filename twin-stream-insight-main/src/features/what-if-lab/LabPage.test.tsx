import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/apiError";

const { fetchWhatIf, fetchSensitivity, downloadText, fetchRecommendation } = vi.hoisted(() => ({
  fetchWhatIf: vi.fn(),
  fetchSensitivity: vi.fn(),
  downloadText: vi.fn(),
  fetchRecommendation: vi.fn(),
}));
vi.mock("@/api/apiClient", () => ({ fetchWhatIf }));
vi.mock("../optimizer-approvals/api", () => ({ fetchRecommendation }));
vi.mock("./sensitivityApi", () => ({ fetchSensitivity }));
vi.mock("./exportCsv", () => ({ downloadText }));
vi.mock("@/lib/errorReporter", () => ({ reportError: vi.fn() }));

import LabPage from "./LabPage";
import { signed } from "./metrics";
import { CAPTURED_SWEEP, whatIfWith } from "./testFixtures";

/** SYNTHETIC `GET /api/optimizer/baseline-recommendation` answer: only `predicted.setpoint_check` is read by the lab. */
const recommendationFor = (physics: string, range: [number, number] | null) => ({
  recommendation: { selected: null, considered: [], note: "" },
  predicted: range === null ? null : { setpoint_check: { physics_version: physics, actuator_range_C: range, proposed_within_actuator_range: true, reference_within_actuator_range: true } },
  persisted: false,
});
const LEGACY_0 = recommendationFor("0", [5, 15]);
const PHYSICS_1 = recommendationFor("1", [16, 25]);

/** SYNTHETIC stand-in for the backend: energy and outlet temperature rise with load, so deltas have a known sign and size. */
const respond = (p: { utilisation: number; outside_temp: number; mode: string; chilled_water_temp: number }, carbonReal = false) =>
  whatIfWith({
    total_energy_kwh: p.utilisation * 20000,
    mean_pue: 1.2 + p.utilisation / 10,
    total_co2_kg: p.utilisation * 9000,
    max_outlet_temp_C: 30 + p.utilisation * 10,
    carbon_data_is_real: carbonReal,
    inputs: { utilisation: p.utilisation, outside_temp_C: p.outside_temp, water_stress: 0, mode: p.mode, chilled_water_temp_C: p.chilled_water_temp },
  });

function Probe() {
  const { search } = useLocation();
  return <output data-testid="search">{search}</output>;
}
const renderAt = (url = "/whatif-lab") => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <LabPage />
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};
const slider = (name: RegExp) => screen.getByRole("slider", { name });
const lastParams = () => fetchWhatIf.mock.calls[fetchWhatIf.mock.calls.length - 1]?.[0];

beforeEach(() => {
  window.localStorage.clear();
  fetchWhatIf.mockReset().mockImplementation(async (p) => respond(p));
  fetchSensitivity.mockReset().mockResolvedValue(CAPTURED_SWEEP);
  downloadText.mockReset();
  fetchRecommendation.mockReset().mockResolvedValue(LEGACY_0);
});
afterEach(cleanup);

describe("What-if lab", () => {
  it("opens with the results labelled a model estimate on simulated data, and runs the backend defaults", async () => {
    renderAt();
    expect(await screen.findByTestId("lab-estimate-label")).toHaveTextContent("model estimate on simulated data");
    expect(await screen.findByTestId("lab-delta-cards")).toBeInTheDocument();
    expect(fetchWhatIf).toHaveBeenCalledWith({ utilisation: 0.65, outside_temp: 22, water_stress: 0, mode: "auto", chilled_water_temp: 7 }, expect.anything());
    // baseline = scenario at open: every delta is "unchanged"
    expect(screen.getByTestId("lab-card-energy")).toHaveAttribute("data-direction", "same");
  });

  it("debounces: a burst of slider moves is one request, sent after the quiet period, and the page says it is updating", async () => {
    renderAt();
    await screen.findByTestId("lab-delta-cards");
    const before = fetchWhatIf.mock.calls.length;
    for (const v of [70, 72, 75, 80]) fireEvent.change(slider(/IT load/), { target: { value: String(v) } });
    expect(screen.getByTestId("lab-pending")).toHaveTextContent(/Updating/);
    expect(fetchWhatIf.mock.calls.length).toBe(before);
    await waitFor(() => expect(lastParams()?.utilisation).toBe(0.8));
    expect(fetchWhatIf.mock.calls.length).toBe(before + 1);
    expect(fetchWhatIf.mock.calls.some((c) => c[0].utilisation === 0.72)).toBe(false);
  });

  it("shows scenario minus baseline: value, signed delta, percent, and a word as well as an arrow", async () => {
    renderAt();
    await screen.findByTestId("lab-delta-cards");
    fireEvent.change(slider(/IT load/), { target: { value: "80" } });
    await waitFor(() => expect(screen.getByTestId("lab-card-energy")).toHaveAttribute("data-direction", "up"));
    expect(screen.getByTestId("lab-delta-energy")).toHaveTextContent(`${signed(16000 - 13000, 0)} kWh`);
    expect(screen.getByTestId("lab-card-energy")).toHaveTextContent(/\+23\.1%/); // 3000 / 13000
    expect(screen.getByTestId("lab-card-energy")).toHaveTextContent(/higher/);
    expect(screen.getByTestId("lab-card-margin")).toHaveAttribute("data-direction", "down"); // hotter outlet, less margin
    expect(screen.getByTestId("lab-card-margin")).toHaveTextContent(/lower/);
  });

  it("labels carbon with the fallback notice when the backend says the intensity is not real, and not when it is", async () => {
    renderAt();
    expect(await screen.findByTestId("lab-carbon-fallback")).toHaveTextContent(/not real grid data/);
    cleanup();
    fetchWhatIf.mockReset().mockImplementation(async (p) => respond(p, true));
    renderAt();
    await screen.findByTestId("lab-delta-cards");
    expect(screen.queryByTestId("lab-carbon-fallback")).toBeNull();
  });

  it("the cooling mode radio sends that mode", async () => {
    renderAt();
    await screen.findByTestId("lab-delta-cards");
    fireEvent.click(screen.getByRole("radio", { name: /Hybrid/ }));
    await waitFor(() => expect(lastParams()?.mode).toBe("hybrid"));
  });

  it("opens from a shared URL, and the address follows the settled inputs", async () => {
    renderAt("/whatif-lab?load=80&mode=hybrid&amb=30&set=9");
    await screen.findByTestId("lab-delta-cards");
    expect(fetchWhatIf).toHaveBeenCalledWith({ utilisation: 0.8, outside_temp: 30, water_stress: 0, mode: "hybrid", chilled_water_temp: 9 }, expect.anything());
    expect((slider(/IT load/) as HTMLInputElement).value).toBe("80");
    fireEvent.change(slider(/IT load/), { target: { value: "55" } });
    await waitFor(() => expect(screen.getByTestId("search").textContent).toMatch(/load=55/));
    expect(screen.getByTestId("search").textContent).toMatch(/mode=hybrid/);
  });

  it("a baseline can be pinned to the current inputs, and appears in the address", async () => {
    renderAt();
    await screen.findByTestId("lab-delta-cards");
    fireEvent.change(slider(/IT load/), { target: { value: "50" } });
    await waitFor(() => expect(lastParams()?.utilisation).toBe(0.5));
    fireEvent.click(screen.getByRole("button", { name: /Use these inputs as baseline/ }));
    await waitFor(() => expect(screen.getByTestId("search").textContent).toMatch(/bload=50/));
    expect(screen.getByTestId("lab-baseline-desc")).toHaveTextContent(/50% IT load/);
  });

  it("saves a scenario, compares it with the baseline, and keeps it across a reload", async () => {
    renderAt();
    await screen.findByTestId("lab-delta-cards");
    fireEvent.change(slider(/IT load/), { target: { value: "80" } });
    await waitFor(() => expect(lastParams()?.utilisation).toBe(0.8));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save current scenario" })).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Busy day" } });
    fireEvent.click(screen.getByRole("button", { name: "Save current scenario" }));
    const list = await screen.findByTestId("lab-saved-list");
    expect(within(list).getByText("Busy day")).toBeInTheDocument();
    expect(screen.getByTestId("lab-compare-table")).toBeInTheDocument();
    cleanup();
    renderAt();
    expect(within(await screen.findByTestId("lab-saved-list")).getByText("Busy day")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete Busy day" }));
    expect(screen.queryByTestId("lab-saved-list")).toBeNull();
  });

  it("exports a CSV of baseline, current and saved scenarios, labelled as an estimate", async () => {
    renderAt();
    await screen.findByTestId("lab-delta-cards");
    await waitFor(() => expect(screen.getByRole("button", { name: "Export CSV" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(downloadText).toHaveBeenCalledTimes(1);
    const [filename, text] = downloadText.mock.calls[0];
    expect(filename).toBe("twingrid-whatif.csv");
    expect(text).toMatch(/^scenario,kind,it_load_pct/);
    expect(text).toContain("model estimate on simulated data");
    expect(text.split("\r\n").filter(Boolean)).toHaveLength(3); // header, baseline, current
  });

  it("copies a link that reopens the same scenario", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    // The link is built from the browser address (window.location), which MemoryRouter does not change: set it as the app would have it.
    window.history.replaceState(null, "", "/whatif-lab");
    renderAt("/whatif-lab?load=80");
    await screen.findByTestId("lab-delta-cards");
    fireEvent.click(screen.getByRole("button", { name: "Copy link" }));
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    // The link carries every scenario parameter (not only the one that changed), so it reopens the same scenario.
    expect(String(writeText.mock.calls[0][0])).toMatch(/\/whatif-lab\?load=80&amb=22&set=7&mode=auto$/);
  });

  it("the sensitivity sweep runs only on request, then shows a tornado sorted by swing, labelled as an estimate", async () => {
    renderAt();
    await screen.findByTestId("lab-delta-cards");
    expect(fetchSensitivity).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Run sensitivity sweep" }));
    const rows = await screen.findByTestId("lab-tornado-rows");
    expect(fetchSensitivity).toHaveBeenCalledTimes(1);
    expect(fetchSensitivity.mock.calls[0][0]).toEqual({ utilisation: 0.65, outside_temp: 22, water_stress: 0, mode: "auto", chilled_water_temp: 7 });
    expect(within(rows).getAllByRole("listitem")[0]).toHaveAttribute("data-testid", "lab-tornado-utilisation");
    expect(screen.getByTestId("lab-sweep-foot")).toHaveTextContent(/model estimate on simulated data/);
    fireEvent.click(screen.getByRole("radio", { name: /Mean PUE/ }));
    expect(within(screen.getByTestId("lab-tornado-rows")).getAllByRole("listitem")).toHaveLength(4);
  });

  it("changed inputs mark the tornado as computed for the old inputs, and offer a re-run", async () => {
    renderAt();
    await screen.findByTestId("lab-delta-cards");
    fireEvent.click(screen.getByRole("button", { name: "Run sensitivity sweep" }));
    await screen.findByTestId("lab-tornado-rows");
    expect(screen.queryByTestId("lab-sweep-stale")).toBeNull();
    fireEvent.change(slider(/IT load/), { target: { value: "90" } });
    await waitFor(() => expect(screen.getByTestId("lab-sweep-stale")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Re-run for current inputs" })).toBeInTheDocument();
  });

  it("a rate-limited sweep is an error state, not a chart", async () => {
    fetchSensitivity.mockRejectedValue(new ApiError({ kind: "rate_limited", status: 429, retryAfterS: 30 }));
    renderAt();
    await screen.findByTestId("lab-delta-cards");
    fireEvent.click(screen.getByRole("button", { name: "Run sensitivity sweep" }));
    await waitFor(() => expect(document.querySelector('[data-state="error"], [data-state="rate_limited"]')).not.toBeNull());
    expect(screen.queryByTestId("lab-tornado-rows")).toBeNull();
  });

  it("a failed scenario run is an error state with retry, never a zero", async () => {
    fetchWhatIf.mockRejectedValue(new ApiError({ kind: "server", status: 500 }));
    renderAt();
    await waitFor(() => expect(document.querySelector('[data-state="error"]')).not.toBeNull());
    expect(screen.queryByTestId("lab-delta-cards")).toBeNull();
  });

  it("reset returns the controls to the default inputs", async () => {
    renderAt("/whatif-lab?load=90");
    await screen.findByTestId("lab-delta-cards");
    fireEvent.click(screen.getByRole("button", { name: "Reset inputs" }));
    expect((slider(/IT load/) as HTMLInputElement).value).toBe("65");
  });
});

describe("What-if lab: set-point range from the server's physics", () => {
  const setpoint = () => slider(/Cooling setpoint/) as HTMLInputElement;

  it("legacy-0: the slider is 5 to 15 and the default is 7", async () => {
    renderAt();
    await screen.findByTestId("lab-delta-cards");
    expect([setpoint().min, setpoint().max, setpoint().value]).toEqual(["5", "15", "7"]);
    expect(screen.getByTestId("lab-setpoint-source")).toHaveTextContent(/5 to 15 °C.*physics 0/);
  });

  it("physics 1: the slider is 16 to 25, the default is inside it, and the legacy 5 to 15 values appear nowhere", async () => {
    fetchRecommendation.mockResolvedValue(PHYSICS_1);
    renderAt();
    await screen.findByTestId("lab-delta-cards");
    expect([setpoint().min, setpoint().max, setpoint().value]).toEqual(["16", "25", "16"]);
    expect((screen.getByLabelText("Cooling setpoint value") as HTMLInputElement).min).toBe("16");
    expect(screen.getByTestId("lab-setpoint-source")).toHaveTextContent(/16 to 25 °C.*physics 1/);
    expect(screen.getByTestId("lab-controls")).not.toHaveTextContent(/5 to 15/);
    expect(fetchWhatIf.mock.calls.every((c) => c[0].chilled_water_temp >= 16 && c[0].chilled_water_temp <= 25)).toBe(true);
    expect(fetchWhatIf.mock.calls.some((c) => c[0].chilled_water_temp === 7)).toBe(false);
  });

  it("physics 1: validation snaps a typed or linked set-point into 16 to 25", async () => {
    fetchRecommendation.mockResolvedValue(PHYSICS_1);
    renderAt("/whatif-lab?set=30&bset=7");
    await screen.findByTestId("lab-delta-cards");
    expect(setpoint().value).toBe("25");
    fireEvent.change(screen.getByLabelText("Cooling setpoint value"), { target: { value: "10" } });
    expect(setpoint().value).toBe("16");
    await waitFor(() => expect(lastParams()?.chilled_water_temp).toBe(16));
    expect(screen.getByTestId("lab-baseline-desc")).toHaveTextContent(/16 °C setpoint/);
  });

  it("the range is read from the server once, with the backend's own what-if defaults as context", async () => {
    renderAt();
    await screen.findByTestId("lab-delta-cards");
    expect(fetchRecommendation).toHaveBeenCalledTimes(1);
    expect(fetchRecommendation.mock.calls[0][0]).toEqual({ utilisation: 0.65, outside_temp: 22, water_stress: 0, mode: "auto", chilled_water_temp: 7, inlet_temp_c: null });
  });

  it("while the range is unknown the lab shows a loading state and runs nothing", async () => {
    fetchRecommendation.mockReturnValue(new Promise(() => undefined));
    renderAt();
    expect(await screen.findByText(/Reading the set-point range/)).toBeInTheDocument();
    expect(screen.queryByTestId("lab-controls")).toBeNull();
    expect(fetchWhatIf).not.toHaveBeenCalled();
  });

  const unavailableCases: { name: string; arrange: () => void }[] = [
    { name: "the request fails", arrange: () => void fetchRecommendation.mockRejectedValue(new ApiError({ kind: "server", status: 500 })) },
    { name: "the server sends no recommendation to read a range from", arrange: () => void fetchRecommendation.mockResolvedValue(recommendationFor("1", null)) },
    { name: "the range is empty", arrange: () => void fetchRecommendation.mockResolvedValue(recommendationFor("1", [20, 20])) },
  ];
  for (const c of unavailableCases) {
    it(`is unavailable, not a guessed range, when ${c.name}`, async () => {
      c.arrange();
      renderAt();
      await waitFor(() => expect(document.querySelector('[data-state="error"], [data-state="unavailable"]')).not.toBeNull());
      expect(screen.queryByTestId("lab-controls")).toBeNull();
      expect(fetchWhatIf).not.toHaveBeenCalled();
    });
  }
});
