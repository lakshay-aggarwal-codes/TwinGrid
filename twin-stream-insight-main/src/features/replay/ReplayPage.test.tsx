import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AlertRecord } from "@/api/models";
import type { TelemetryGap, TelemetrySample } from "@/telemetry/history/schema";

const { fetchFacilityId, fetchTelemetrySamples, fetchTelemetryGaps, fetchAlerts } = vi.hoisted(() => ({
  fetchFacilityId: vi.fn(),
  fetchTelemetrySamples: vi.fn(),
  fetchTelemetryGaps: vi.fn(),
  fetchAlerts: vi.fn(),
}));
vi.mock("@/api/apiClient", () => ({ fetchFacilityId, fetchTelemetrySamples, fetchTelemetryGaps, fetchAlerts }));
vi.mock("@/lib/errorReporter", () => ({ reportError: vi.fn() }));
// The 3D scene needs WebGL; the replay page's own behaviour is what is under test here.
vi.mock("@/three/TwinScene", () => ({ TwinScene: () => <div data-testid="twin-scene-stub" /> }));
// The page reads the live feed only for its own freshness line; no frame is ever supplied.
vi.mock("@/telemetry/useFeed", () => ({
  useFeed: (select: (v: unknown) => unknown) => select({ frame: null, freshness: { state: "live", ageMs: 0, staleAfterMs: 5000, lastReceivedAt: 0 }, transport: {} }),
}));

import ReplayPage from "./ReplayPage";

const MIN = 60_000;
const HOUR = 3_600_000;
const NOW = Date.now();
const T0 = Math.floor((NOW - 3 * HOUR) / 1000) * 1000;
const iso = (ms: number) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, "Z");

/** SYNTHETIC: one sample every 5 minutes for an hour from T0; the value is 100 + (steps since T0), so a lookup is easy to read. */
const samples = (): TelemetrySample[] =>
  Array.from({ length: 12 }, (_, i) => ({ ts_event: iso(T0 + i * 5 * MIN), ts_ingest: iso(T0 + i * 5 * MIN), value: 100 + i, origin: "simulated", stream_id: "live", quality: "ok", invalid_reason: null }));

const page = (id: string, items: TelemetrySample[]) => ({ external_id: id, unit: "kW", sampling_interval_s: 300, stream: "live", quality: "any", items, next_cursor: null });
const gaps = (id: string, list: TelemetryGap[] = []) => ({ external_id: id, stream: "live", sampling_interval_s: 300, threshold_s: null, gaps: list, truncated: false });

const alert = (id: number, ms: number, severity = "CRITICAL"): AlertRecord => ({
  id, created_at: iso(ms), type: "anomaly", message: "synthetic", severity, score: 1, alert: true, acknowledged: false, acknowledged_by: null, acknowledged_at: null,
});

function Probe() {
  const { search } = useLocation();
  return <output data-testid="search">{search}</output>;
}

const renderAt = (url = "/replay") => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <ReplayPage />
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

beforeEach(() => {
  fetchFacilityId.mockReset().mockResolvedValue(1);
  fetchTelemetrySamples.mockReset().mockImplementation(async (id: string) => page(id, samples()));
  fetchTelemetryGaps.mockReset().mockImplementation(async (id: string) => gaps(id));
  fetchAlerts.mockReset().mockResolvedValue([]);
});
afterEach(cleanup);

describe("Replay page", () => {
  it("opens live: five stored series are requested from the history endpoints and drawn, and the banner does not claim replay", async () => {
    renderAt();
    expect(await screen.findByTestId("replay-charts")).toBeInTheDocument();
    expect(screen.getAllByTestId(/^replay-chart-(?!at)/)).toHaveLength(5);
    expect(fetchTelemetrySamples.mock.calls.map((c) => c[0]).sort()).toEqual(["fac1.humidity_pct", "fac1.it_power_kw", "fac1.server_outlet_temp_C", "fac1.water_flow_lpm", "fac1.water_pressure_bar"]);
    const [, params] = fetchTelemetrySamples.mock.calls[0];
    expect(params.limit).toBe(5000);
    expect(params.to).toMatch(/Z$/);
    expect(Date.parse(params.to) - Date.parse(params.from)).toBe(6 * HOUR);
    expect(screen.getByTestId("replay-banner")).toHaveAttribute("data-replaying", "false");
    expect(screen.queryByText(/REPLAY — not live/)).toBeNull();
    expect(screen.getByRole("slider", { name: /Replay time/ })).toHaveAttribute("aria-valuetext", "Live");
  });

  it("Play starts a replay: the persistent banner says REPLAY — not live, and the values come from stored samples; LIVE returns", async () => {
    renderAt();
    await screen.findByTestId("replay-charts");
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    const banner = screen.getByTestId("replay-banner");
    expect(banner).toHaveAttribute("data-replaying", "true");
    expect(within(banner).getByText(/REPLAY — not live/)).toBeInTheDocument();
    expect(screen.getByTestId("replay-kpis")).toHaveAttribute("data-source", "replay");
    fireEvent.click(within(banner).getByRole("button", { name: "Return to LIVE" }));
    expect(screen.getByTestId("replay-banner")).toHaveAttribute("data-replaying", "false");
    expect(screen.getByTestId("replay-kpis")).toHaveAttribute("data-source", "live");
  });

  it("playback advances the cursor at the chosen speed", async () => {
    renderAt();
    await screen.findByTestId("replay-charts");
    fireEvent.click(screen.getByRole("radio", { name: "60×" }));
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    const slider = screen.getByRole("slider", { name: /Replay time/ });
    const start = Number(slider.getAttribute("aria-valuenow"));
    await waitFor(() => expect(Number(slider.getAttribute("aria-valuenow"))).toBeGreaterThan(start));
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();
  });

  it("offers exactly the speeds 1× to 60×", async () => {
    renderAt();
    await screen.findByTestId("replay-charts");
    const radios = within(screen.getByRole("radiogroup", { name: "Replay speed" })).getAllByRole("radio");
    expect(radios.map((r) => r.textContent)).toEqual(["1×", "2×", "5×", "10×", "30×", "60×"]);
  });

  it("?t= opens a replay at that time and shows the held stored sample, with its own timestamp", async () => {
    const t = T0 + 22 * MIN; // between the samples at +20 min (104) and +25 min (105)
    renderAt(`/replay?t=${encodeURIComponent(iso(t))}`);
    await screen.findByTestId("replay-charts");
    expect(screen.getByTestId("replay-banner")).toHaveAttribute("data-replaying", "true");
    const cell = screen.getByTestId("replay-kpi-it_power_kw");
    expect(cell).toHaveAttribute("data-kind", "value");
    expect(cell).toHaveTextContent("104");
    expect(cell).toHaveTextContent(/Held from the sample at/);
  });

  it("a stored gap is shown as no data, never as a value or a line across it", async () => {
    const gap: TelemetryGap = { start: iso(T0 + 25 * MIN), end: iso(T0 + 45 * MIN), duration_s: 1200 };
    fetchTelemetryGaps.mockImplementation(async (id: string) => gaps(id, [gap]));
    fetchTelemetrySamples.mockImplementation(async (id: string) => page(id, samples().filter((s) => { const ms = Date.parse(s.ts_event); return ms <= T0 + 25 * MIN || ms >= T0 + 45 * MIN; })));
    renderAt(`/replay?t=${encodeURIComponent(iso(T0 + 35 * MIN))}`);
    await screen.findByTestId("replay-charts");
    const cell = screen.getByTestId("replay-kpi-it_power_kw");
    expect(cell).toHaveAttribute("data-kind", "gap");
    expect(cell).toHaveTextContent(/No data: stored gap/);
    expect(screen.getAllByTestId("replay-gap-band").length).toBeGreaterThan(0);
  });

  it("before the first stored sample there is no value, and it says when the data starts", async () => {
    renderAt(`/replay?t=${encodeURIComponent(iso(T0 - HOUR))}`);
    await screen.findByTestId("replay-charts");
    expect(screen.getByTestId("replay-kpi-it_power_kw")).toHaveAttribute("data-kind", "before-start");
    expect(screen.getByTestId("replay-kpi-it_power_kw")).toHaveTextContent(/first stored sample is at/);
  });

  it("an empty window is stated as such: no charts, and the time controls still work", async () => {
    fetchTelemetrySamples.mockImplementation(async (id: string) => page(id, []));
    renderAt();
    expect(await screen.findByText(/No stored telemetry in this window/)).toBeInTheDocument();
    expect(screen.queryByTestId("replay-charts")).toBeNull();
    fireEvent.keyDown(screen.getByRole("slider", { name: /Replay time/ }), { key: "ArrowLeft" });
    expect(screen.getByTestId("replay-banner")).toHaveAttribute("data-replaying", "true");
    expect(screen.getByTestId("replay-kpi-it_power_kw")).toHaveAttribute("data-kind", "none");
  });

  it("one failing measurand is named and the others still replay", async () => {
    fetchTelemetrySamples.mockImplementation(async (id: string) => {
      if (id.endsWith("humidity_pct")) throw new Error("boom");
      return page(id, samples());
    });
    renderAt();
    expect(await screen.findByText(/Could not load: Humidity/)).toBeInTheDocument();
    expect(screen.getAllByTestId(/^replay-chart-(?!at)/)).toHaveLength(4);
  });

  it("alert pins sit on the timeline with a shape and a label, and jump the cursor to the alert", async () => {
    fetchAlerts.mockResolvedValue([alert(7, T0 + 30 * MIN, "CRITICAL"), alert(6, T0 + 10 * MIN, "WARNING")]);
    renderAt();
    const pins = await screen.findAllByTestId("replay-pin");
    expect(pins).toHaveLength(2);
    expect(pins[1]).toHaveAccessibleName(/Alert 7, critical \(triangle\)/);
    fireEvent.click(pins[1]);
    const slider = screen.getByRole("slider", { name: /Replay time/ });
    expect(Number(slider.getAttribute("aria-valuenow"))).toBe(T0 + 30 * MIN);
    fireEvent.click(screen.getByRole("button", { name: "Previous alert" }));
    expect(Number(slider.getAttribute("aria-valuenow"))).toBe(T0 + 10 * MIN);
  });

  it("compare mode shows B minus A per measurand, with a word as well as an arrow, and marks a side with no data as unavailable", async () => {
    renderAt(`/replay?t=${encodeURIComponent(iso(T0 + 20 * MIN))}&tb=${encodeURIComponent(iso(T0 + 40 * MIN))}`);
    await screen.findByTestId("replay-charts");
    const row = await screen.findByTestId("replay-delta-it_power_kw");
    expect(row).toHaveAttribute("data-status", "ok");
    expect(row).toHaveTextContent(/\+4/); // 108 - 104
    expect(row).toHaveTextContent(/increase/);
    cleanup();
    renderAt(`/replay?t=${encodeURIComponent(iso(T0 + 20 * MIN))}&tb=${encodeURIComponent(iso(T0 - 2 * HOUR))}`);
    await screen.findByTestId("replay-charts");
    expect(await screen.findByTestId("replay-delta-it_power_kw")).toHaveAttribute("data-status", "unavailable");
  });

  it("the URL follows the cursor (?t=) and drops it again on LIVE; other parameters are kept", async () => {
    renderAt("/replay?rack=R1");
    await screen.findByTestId("replay-charts");
    fireEvent.keyDown(screen.getByRole("slider", { name: /Replay time/ }), { key: "Home" });
    await waitFor(() => expect(screen.getByTestId("search").textContent).toMatch(/t=/));
    expect(screen.getByTestId("search").textContent).toMatch(/rack=R1/);
    fireEvent.click(screen.getAllByRole("button", { name: "Return to LIVE" })[0]);
    await waitFor(() => expect(screen.getByTestId("search").textContent).not.toMatch(/t=/));
    expect(screen.getByTestId("search").textContent).toMatch(/rack=R1/);
  });

  it("a facility failure is an error state with no history requested", async () => {
    fetchFacilityId.mockRejectedValue(new Error("down"));
    renderAt();
    await waitFor(() => expect(document.querySelector('[data-state="error"]')).not.toBeNull());
    expect(fetchTelemetrySamples).not.toHaveBeenCalled();
  });

  it("is replaced by a plain notice when the history view is switched off at build time", async () => {
    vi.stubEnv("VITE_TELEMETRY_HISTORY", "off");
    renderAt();
    expect(await screen.findByTestId("replay-disabled")).toBeInTheDocument();
    expect(fetchFacilityId).not.toHaveBeenCalled();
    vi.unstubAllEnvs();
  });
});

describe("Replay 3D view", () => {
  it("is mounted without a live frame, says the racks are not tinted, and lists the replayed values beside it", async () => {
    renderAt(`/replay?t=${encodeURIComponent(iso(T0 + 20 * MIN))}`);
    expect(await screen.findByTestId("twin-scene-stub")).toBeInTheDocument();
    expect(screen.getByTestId("replay-scene")).toHaveTextContent(/Racks are not tinted/);
    await waitFor(() => expect(screen.getByTestId("replay-scene-readouts")).toHaveTextContent(/104/));
  });
});
