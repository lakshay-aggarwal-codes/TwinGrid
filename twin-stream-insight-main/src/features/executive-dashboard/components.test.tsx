import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WhatIfResult } from "@/hooks/useWhatIf";
import { CAPTURED_BASELINES_ONLY } from "@/evaluation/testFixtures";
import type { LiveStatePayload } from "@/api/apiClient";

const { run, savings, open, live } = vi.hoisted(() => ({
  run: { current: { status: "loading" } as unknown },
  savings: { current: { state: "loading", facts: null, reason: undefined } as unknown },
  open: { current: null as unknown },
  live: { current: true },
}));
vi.mock("./useExecData", () => ({
  useModelRun: () => run.current as WhatIfResult,
  useSavings: () => savings.current,
  useOpenAlerts: () => open.current,
  useFeedLive: () => live.current,
}));
vi.mock("@/lib/errorReporter", () => ({ reportError: vi.fn() }));

import KpiCards from "./KpiCards";
import GoalRings from "./GoalRings";
import InsightsFeed from "./InsightsFeed";
import feature from "./index";
import { createFeatureRegistry } from "../registry";
import { GOALS_KEY } from "./goals";
import { recordFrame, resetLiveSeries } from "./liveStore";
import { reloadGoals, resetGoals } from "./goalsStore";
import { savingsFacts } from "./kpis";
import { REAL_WHATIF_065_22_04_AUTO_7 } from "./testFixtures";

const ctx = { context: {} };
const T = Date.UTC(2026, 9, 15, 10, 0, 0);

/** SYNTHETIC frames: round numbers, 3 s apart. */
function feed(n: number, over: (i: number) => Partial<LiveStatePayload> = () => ({})) {
  for (let i = 0; i < n; i++) {
    recordFrame(
      { pue: 1.25, it_power_kw: 400, cooling_power_kw: 100, total_power_kw: 500, server_outlet_temp_C: 30, carbon_intensity_gco2_per_kwh: 475, carbon_data_is_real: false, seq: i + 1, ...over(i) } as LiveStatePayload,
      T + i * 3000,
    );
  }
}

const ready = (data = REAL_WHATIF_065_22_04_AUTO_7, extra: object = {}): WhatIfResult => ({ status: "ready", data, params: {} as never, ...extra }) as WhatIfResult;

beforeEach(() => {
  window.localStorage.clear();
  resetGoals();
  resetLiveSeries();
  run.current = ready();
  savings.current = { state: "ready", facts: savingsFacts(CAPTURED_BASELINES_ONLY), reason: undefined };
  open.current = null;
  live.current = true;
});
afterEach(cleanup);

describe("KpiCards", () => {
  it("shows the five KPIs with their bases; fallback carbon is labelled", () => {
    feed(5, () => ({ pue: 1.31 }));
    render(<KpiCards {...ctx} />);
    expect(screen.getByTestId("kpi-pue-value").textContent).toBe("1.31");
    expect(screen.getByTestId("kpi-it-energy-value").textContent).toBe("9,480");
    expect(screen.getByTestId("kpi-total-energy-value").textContent).toBe("12,528");
    expect(screen.getByTestId("kpi-carbon-value").textContent).toBe("5,951");
    expect(screen.getByText("Carbon (fallback)")).toBeTruthy();
    expect(screen.getByText(/Fallback carbon intensity/)).toBeTruthy();
    expect(screen.getByTestId("kpi-savings-value").textContent).toBe("2.8");
    expect(screen.getByText("less energy than the baseline")).toBeTruthy();
    expect(screen.getByText(/claim allowed: none/)).toBeTruthy();
    expect(screen.getByText(/Simulated data/)).toBeTruthy();
  });

  it("draws sparklines from live samples and says it is collecting before there are two", () => {
    feed(1);
    const { unmount } = render(<KpiCards {...ctx} />);
    expect(screen.queryAllByTestId("exec-spark")).toHaveLength(0);
    expect(screen.getAllByText(/collecting live samples/).length).toBeGreaterThan(0);
    unmount();
    feed(5);
    render(<KpiCards {...ctx} />);
    expect(screen.getAllByTestId("exec-spark").length).toBeGreaterThanOrEqual(3);
  });

  it("states NOT MEASURED, with the reason, instead of a number", () => {
    run.current = ready({ ...REAL_WHATIF_065_22_04_AUTO_7, wue: 0 });
    savings.current = { state: "none", facts: null, reason: "No policy-evaluation report has been run." };
    render(<KpiCards {...ctx} />);
    expect(screen.getByTestId("kpi-it-energy-value").textContent).toBe("NOT MEASURED");
    expect(screen.getByTestId("kpi-savings-value").textContent).toBe("NOT MEASURED");
    expect(screen.getByText("No policy-evaluation report has been run.")).toBeTruthy();
    expect(screen.getByTestId("kpi-pue-value").textContent).toBe("NOT MEASURED");
  });

  it("loading and error states replace the model-derived cards, never zeros", () => {
    run.current = { status: "loading" };
    const { unmount } = render(<KpiCards {...ctx} />);
    expect(screen.getAllByText("Loading the 24 h model run…")).toHaveLength(3);
    unmount();
    run.current = { status: "error", kind: "server" };
    render(<KpiCards {...ctx} />);
    expect(screen.queryByTestId("kpi-total-energy-value")).toBeNull();
    expect(screen.getAllByRole("alert").length + screen.getAllByRole("status").length).toBeGreaterThan(0);
  });

  it("a failed refresh keeps the earlier numbers and says so; a stale feed marks PUE as last known", () => {
    run.current = ready(REAL_WHATIF_065_22_04_AUTO_7, { refreshFailed: true });
    live.current = false;
    feed(3);
    render(<KpiCards {...ctx} />);
    expect(screen.getByTestId("kpi-total-energy-value").textContent).toBe("12,528");
    expect(screen.getAllByText(/Last refresh failed/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Last known value/)).toBeTruthy();
  });
});

describe("GoalRings", () => {
  it("shows within/over/no target in words, with defaults only for PUE and outlet", () => {
    feed(3, () => ({ pue: 1.4 }));
    render(<GoalRings {...ctx} />);
    expect(screen.getByTestId("goal-pue-status").textContent).toContain("Over target");
    expect(screen.getByTestId("goal-outlet-status").textContent).toContain("Within target");
    expect(screen.getByTestId("goal-energy-status").textContent).toContain("No target set");
  });

  it("edits a target with the keyboard, refuses bad input, and cancels on Escape", () => {
    feed(3);
    render(<GoalRings {...ctx} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit the PUE target" }));
    const input = screen.getByLabelText(/PUE target/);
    fireEvent.change(input, { target: { value: "abc" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByRole("alert").textContent).toBe("Enter a number.");
    fireEvent.change(input, { target: { value: "1.2" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByTestId("goal-pue-status").textContent).toContain("Over target (target \u2264 1.20)");
    expect(JSON.parse(window.localStorage.getItem(GOALS_KEY) as string).pue).toBe(1.2);
    fireEvent.click(screen.getByRole("button", { name: "Edit the PUE target" }));
    fireEvent.keyDown(screen.getByLabelText(/PUE target/), { key: "Escape" });
    expect(screen.queryByLabelText(/PUE target/)).toBeNull();
  });

  it("sets and clears an energy target; the model value is the ring's value", () => {
    render(<GoalRings {...ctx} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit the Total energy (24 h model) target" }));
    fireEvent.change(screen.getByLabelText(/Total energy/), { target: { value: "13000" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByTestId("goal-energy-status").textContent).toContain("Within target");
    fireEvent.click(screen.getByRole("button", { name: "Edit the Total energy (24 h model) target" }));
    fireEvent.change(screen.getByLabelText(/Total energy/), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByTestId("goal-energy-status").textContent).toContain("No target set");
  });

  it("targets survive a reload of the store", () => {
    window.localStorage.setItem(GOALS_KEY, JSON.stringify({ pue: 1.1 }));
    reloadGoals();
    feed(3);
    render(<GoalRings {...ctx} />);
    expect(screen.getByTestId("goal-pue-status").textContent).toContain("target \u2264 1.10");
  });

  it("no data is stated as such, never a zero ring", () => {
    run.current = { status: "loading" };
    render(<GoalRings {...ctx} />);
    expect(screen.getByTestId("goal-pue-status").textContent).toContain("No data yet");
    expect(screen.getAllByText("NOT MEASURED").length).toBeGreaterThanOrEqual(2);
  });
});

describe("InsightsFeed", () => {
  it("explains why there is no trend yet", () => {
    feed(4);
    render(<InsightsFeed {...ctx} />);
    expect(screen.getByTestId("insights-warming").textContent).toContain("This session has 4 samples over 9 s");
    expect(screen.getByText(/Rule-based, not AI · no language model is called/)).toBeTruthy();
  });

  it("lists rule-based statements, each labelled with its rule and data window", () => {
    feed(61, (i) => ({ pue: i < 12 ? 1.2 : i >= 49 ? 1.26 : 1.23, it_power_kw: i < 12 ? 400 : i >= 49 ? 376 : 390 }));
    open.current = { open: 2, listed: 50 };
    render(<InsightsFeed {...ctx} />);
    const items = screen.getAllByRole("listitem");
    expect(items.length).toBeGreaterThanOrEqual(3);
    for (const li of items) {
      expect(within(li).getByText("Rule-based, not AI")).toBeTruthy();
      expect(li.textContent).toMatch(/Rule: .* · Data window: /);
    }
    expect(screen.getByText(/PUE rose 5\.0% over the last 3 min/)).toBeTruthy();
    expect(screen.getByText(/2 unacknowledged alerts among the last 50 recorded/)).toBeTruthy();
    expect(screen.getAllByText(/Needs attention:/).length).toBeGreaterThan(0);
    expect(screen.queryByTestId("insights-warming")).toBeNull();
  });

  it("re-renders when new live frames arrive", () => {
    feed(3);
    render(<InsightsFeed {...ctx} />);
    expect(screen.getByTestId("insights-warming").textContent).toContain("3 samples");
    act(() => feed(1, () => ({ seq: 99 })));
    expect(screen.getByTestId("insights-warming").textContent).toContain("4 samples");
  });
});

describe("registration", () => {
  it("adds three dashboard widgets in order and nothing else", () => {
    const r = createFeatureRegistry([feature], { onReject: () => undefined });
    expect(r.rejected).toEqual([]);
    expect(r.slotWidgets("dashboard", "viewer")).toHaveLength(3);
    expect(r.slotWidgets("dashboard", "viewer").map((w) => w.order)).toEqual([10, 20, 30]);
    expect(r.allRoutes()).toEqual([]);
    expect(r.navGroups("viewer")).toEqual([]);
  });
});
