import "@/test/resizeObserver";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { FALLBACK_LAYOUT } from "@/three/facilityLayout";
import { inspectorBridge } from "@/three/inspectorBridge";
import { frameState } from "@/three/feedTestUtils";
import type { FacilityLayout } from "@/three/facilityLayout";

const view = vi.hoisted(() => ({ value: null as unknown }));
vi.mock("@/telemetry/useFeed", () => ({ useFeed: (select: (v: unknown) => unknown) => select(view.value) }));

const alerts = vi.hoisted(() => ({ state: { status: "loading" } as unknown }));
vi.mock("@/state/useApiQuery", () => ({ useApiQuery: () => ({ state: alerts.state, refetch: vi.fn() }) }));

const history = vi.hoisted(() => ({ facility: { status: "loading" } as unknown, samples: { status: "loading" } as unknown }));
vi.mock("@/telemetry/history/useTelemetryHistory", () => ({
  useFacilityId: () => ({ state: history.facility, refetch: vi.fn() }),
  useTelemetryHistory: () => ({ state: history.samples, refetch: vi.fn() }),
}));

import RackList from "./RackList";
import ViewControls from "./ViewControls";
import RackReadouts from "./RackReadouts";
import RackTooltip from "./RackTooltip";
import { useInspectorHost } from "./useInspectorHost";

const live = (extra = {}) => {
  view.value = {
    frame: { value: frameState(extra), provenance: { origin: "simulated" }, receivedAt: 1 },
    freshness: { state: "live", ageMs: 500, staleAfterMs: 9000, lastReceivedAt: 1 },
    transport: { detail: null },
  };
};

const first = FALLBACK_LAYOUT.racks[0].rackId;
const second = FALLBACK_LAYOUT.racks[1].rackId;

beforeEach(() => {
  live();
  alerts.state = { status: "loading" };
  history.facility = { status: "loading" };
  history.samples = { status: "loading" };
});
afterEach(() => inspectorBridge.reset());

function actionsSpy() {
  const spy = { selectRack: vi.fn(), setMode: vi.fn(), flyToPreset: vi.fn() };
  inspectorBridge.registerActions(spy);
  return spy;
}

describe("RackList (keyboard alternative to the canvas)", () => {
  it("lists every rack with one tab stop, moves with the arrows and selects with Enter", () => {
    const spy = actionsSpy();
    render(<RackList context={{ rackId: null }} />);
    const items = screen.getAllByRole("button");
    expect(items).toHaveLength(FALLBACK_LAYOUT.racks.length);
    expect(items.filter((b) => b.tabIndex === 0)).toHaveLength(1);

    const a = screen.getByTestId(`rack-item-${first}`);
    a.focus();
    fireEvent.keyDown(a, { key: "ArrowDown" });
    expect(screen.getByTestId(`rack-item-${second}`)).toHaveFocus();
    fireEvent.keyDown(screen.getByTestId(`rack-item-${second}`), { key: "End" });
    expect(screen.getByTestId(`rack-item-${FALLBACK_LAYOUT.racks[FALLBACK_LAYOUT.racks.length - 1].rackId}`)).toHaveFocus();

    fireEvent.click(screen.getByTestId(`rack-item-${second}`));
    expect(spy.selectRack).toHaveBeenCalledWith(second);
  });

  it("marks the selected rack with text and aria-current, not colour alone", () => {
    render(<RackList context={{ rackId: second }} />);
    const item = screen.getByTestId(`rack-item-${second}`);
    expect(item).toHaveAttribute("aria-current", "true");
    expect(item.textContent).toContain("▶");
    expect(item.textContent).toContain("(selected)");
  });
});

describe("ViewControls", () => {
  it("flies to a preset and toggles a layer on and off", () => {
    const spy = actionsSpy();
    render(<ViewControls context={{}} />);
    fireEvent.click(screen.getByTestId("preset-top-down"));
    expect(spy.flyToPreset).toHaveBeenCalledWith("top-down");

    fireEvent.click(screen.getByTestId("layer-power"));
    expect(spy.setMode).toHaveBeenCalledWith("energy");
    act(() => inspectorBridge.publish({ mode: "energy" }));
    expect(screen.getByTestId("layer-power")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByTestId("layer-power"));
    expect(spy.setMode).toHaveBeenLastCalledWith("physical");
  });

  it("shows a legend with shape cues and marks the current band only from a current reading", () => {
    act(() => inspectorBridge.publish({ mode: "energy" }));
    live({ pue: 1.3 });
    const { rerender } = render(<ViewControls context={{}} />);
    const legend = screen.getByTestId("layer-legend");
    expect(legend.textContent).toContain("◆");
    expect(legend.querySelectorAll("[data-active='true']")).toHaveLength(1);

    view.value = { ...(view.value as object), freshness: { state: "stale", ageMs: 60_000, staleAfterMs: 9000, lastReceivedAt: 1 } };
    rerender(<ViewControls context={{}} />);
    expect(screen.getByTestId("layer-legend").querySelectorAll("[data-active='true']")).toHaveLength(0);
    expect(screen.getByText(/nothing is marked as current/i)).toBeInTheDocument();
  });
});

describe("RackReadouts", () => {
  it("renders nothing without a selection", () => {
    const { container } = render(<RackReadouts context={{ rackId: null }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("labels the readings facility-wide, says the health score is NOT MEASURED, and shows loading states", () => {
    render(<RackReadouts context={{ rackId: first }} />);
    expect(screen.getByTestId("facility-wide-note").textContent).toMatch(/not specific to this rack/i);
    expect(screen.getByTestId("reading-temperature").textContent).toContain("30.0 °C");
    expect(screen.getByTestId("reading-power").textContent).toContain("300.0 kW");
    expect(screen.getByTestId("reading-utilisation").textContent).toContain("50 %");
    expect(screen.getByTestId("health-score").textContent).toContain("NOT MEASURED");
  });

  it("shows last known values with their age, and no numbers when there is no frame", () => {
    view.value = {
      frame: { value: frameState(), provenance: {}, receivedAt: 1 },
      freshness: { state: "stale", ageMs: 42_000, staleAfterMs: 9000, lastReceivedAt: 1 },
      transport: { detail: null },
    };
    const { rerender } = render(<RackReadouts context={{ rackId: first }} />);
    expect(screen.getByTestId("readouts-last-known")).toBeInTheDocument();

    view.value = { frame: null, freshness: { state: "connecting", ageMs: null, staleAfterMs: 9000, lastReceivedAt: null }, transport: { detail: null } };
    rerender(<RackReadouts context={{ rackId: first }} />);
    expect(screen.queryByTestId("reading-temperature")).toBeNull();
  });

  it("counts open alerts and draws the 30-minute sparkline from the history data", () => {
    alerts.state = { status: "ready", data: [{ acknowledged: false }, { acknowledged: true }] };
    history.facility = { status: "ready", data: 1 };
    history.samples = {
      status: "ready",
      data: {
        sensorId: "fac1.server_outlet_temp_C",
        unit: "°C",
        samplingIntervalS: 60,
        thresholdS: 120,
        items: [
          { ts_event: "2026-10-14T10:00:00Z", value: 20, origin: "simulated", quality: "ok" },
          { ts_event: "2026-10-14T10:01:00Z", value: 21, origin: "simulated", quality: "ok" },
        ],
        gaps: [],
        gapsTruncated: false,
        moreAvailable: false,
        pagesLoaded: 1,
      },
    };
    render(<RackReadouts context={{ rackId: first }} />);
    expect(screen.getByTestId("open-alerts").textContent).toContain("1");
    expect(screen.getByTestId("sparkline")).toHaveAttribute("role", "img");
    expect(screen.getByText(/origin: simulated/i)).toBeInTheDocument();
  });

  it("says plainly when there are no stored samples", () => {
    history.facility = { status: "ready", data: 1 };
    history.samples = { status: "empty" };
    render(<RackReadouts context={{ rackId: first }} />);
    expect(screen.getByText(/No stored samples in the last 30 minutes/i)).toBeInTheDocument();
  });
});

describe("RackTooltip", () => {
  it("appears for the hovered rack, names it, and disappears again (no per-frame state)", () => {
    render(<RackTooltip context={{}} />);
    expect(screen.queryByTestId("rack-tooltip")).toBeNull();
    act(() => inspectorBridge.publish({ hoveredRackId: first }));
    expect(screen.getByTestId("rack-tooltip").textContent).toContain("Zone A, row 1, rack 1");
    act(() => inspectorBridge.publish({ hoveredRackId: null }));
    expect(screen.queryByTestId("rack-tooltip")).toBeNull();
  });
});

describe("useInspectorHost (selection and ?rack= URL)", () => {
  function fakeWindow(search: string) {
    const loc = { search, pathname: "/live", hash: "" };
    const history = {
      state: null,
      replaceState: vi.fn((_s: unknown, _t: string, url: string) => {
        loc.search = url.slice(url.indexOf("?") === -1 ? url.length : url.indexOf("?"));
      }),
    };
    return { location: loc, history } as unknown as Pick<Window, "location" | "history"> & { history: { replaceState: ReturnType<typeof vi.fn> } };
  }

  const baseHandlers = () => ({ onFocusRack: vi.fn(), onDeselect: vi.fn(), onSetMode: vi.fn(), onFocusPreset: vi.fn() });
  const opts = (win: ReturnType<typeof fakeWindow>, extra: Partial<Parameters<typeof useInspectorHost>[0]> = {}) => ({
    layout: FALLBACK_LAYOUT as FacilityLayout,
    topologyLoading: false,
    selectedRackId: null as string | null,
    mode: "physical" as const,
    ...baseHandlers(),
    win,
    ...extra,
  });

  it("selects the rack named in the URL once the topology is known, and keeps the URL", () => {
    const win = fakeWindow(`?rack=${first}`);
    const o = opts(win);
    const { rerender } = renderHook((p) => useInspectorHost(p), { initialProps: o });
    expect(o.onFocusRack).toHaveBeenCalledWith(first);
    expect(win.history.replaceState).not.toHaveBeenCalled();
    rerender({ ...o, selectedRackId: first });
    expect(win.location.search).toBe(`?rack=${first}`);
  });

  it("waits while the topology is loading, and drops an unknown id", () => {
    const win = fakeWindow("?rack=nope&x=1");
    const o = opts(win, { topologyLoading: true });
    const { rerender } = renderHook((p) => useInspectorHost(p), { initialProps: o });
    expect(o.onFocusRack).not.toHaveBeenCalled();
    rerender({ ...o, topologyLoading: false });
    expect(o.onFocusRack).not.toHaveBeenCalled();
    expect(win.location.search).toBe("?x=1");
  });

  it("writes the selection to the URL and removes it on deselect", () => {
    const win = fakeWindow("");
    const o = opts(win);
    const { rerender } = renderHook((p) => useInspectorHost(p), { initialProps: o });
    rerender({ ...o, selectedRackId: second });
    expect(win.location.search).toBe(`?rack=${second}`);
    rerender({ ...o, selectedRackId: null });
    expect(win.location.search).toBe("");
  });

  it("publishes to the bridge and registers handlers that reach the page", () => {
    const win = fakeWindow("");
    const o = opts(win, { selectedRackId: first, mode: "thermal" });
    renderHook(() => useInspectorHost(o));
    expect(inspectorBridge.getState()).toMatchObject({ selectedRackId: first, mode: "thermal" });
    inspectorBridge.actions.selectRack(second);
    inspectorBridge.actions.selectRack(null);
    inspectorBridge.actions.flyToPreset("hot-aisle");
    expect(o.onFocusRack).toHaveBeenCalledWith(second);
    expect(o.onDeselect).toHaveBeenCalled();
    expect(o.onFocusPreset).toHaveBeenCalledWith("hot-aisle");
  });
});
