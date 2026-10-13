import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { FeedStoreContext } from "@/telemetry/useFeed";
import type { FeedStore, FeedView } from "@/telemetry/feedStore";
import { createFeatureRegistry } from "../registry";
import feature from "./index";
import HeaderSimulatedBadge, { SimulatedDataBadge } from "./SimulatedDataBadge";
import { isSimulatedOrigin } from "./badgeState";

function storeWithOrigin(origin: string | undefined, hasFrame = true): FeedStore {
  const view = { frame: hasFrame ? { provenance: { origin } } : null } as unknown as FeedView;
  return { getView: () => view, subscribe: () => () => undefined } as unknown as FeedStore;
}

const renderWidget = (store: FeedStore | null) =>
  render(
    <FeedStoreContext.Provider value={store}>
      <HeaderSimulatedBadge />
    </FeedStoreContext.Provider>,
  );

describe("isSimulatedOrigin", () => {
  it("is true only for the exact backend value 'simulated'", () => {
    expect(isSimulatedOrigin("simulated")).toBe(true);
    for (const other of [undefined, null, "", "measured", "replayed", "Simulated", "SIMULATED", " simulated", "sim", 1, {}]) {
      expect(isSimulatedOrigin(other)).toBe(false);
    }
  });
});

describe("<SimulatedDataBadge>", () => {
  it("shows the words 'Simulated data' with the simulated marker for origin=simulated", () => {
    render(<SimulatedDataBadge origin="simulated" />);
    expect(screen.getByText("Simulated data")).toBeInTheDocument();
    const badge = screen.getByTestId("simulated-data-badge");
    expect(badge.querySelector("[data-origin='simulated']")).not.toBeNull();
    expect(badge.querySelector("svg[data-prov-icon='origin-simulated']")).not.toBeNull(); // icon cue, not colour alone
  });

  it.each([undefined, null, "measured", "replayed", "something-new"])("renders nothing for origin %s", (origin) => {
    const { container } = render(<SimulatedDataBadge origin={origin as string | null | undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("header widget (driven by the live feed)", () => {
  it("shows the badge when the latest frame says simulated", () => {
    renderWidget(storeWithOrigin("simulated"));
    expect(screen.getByText("Simulated data")).toBeInTheDocument();
  });

  it("shows nothing before the first frame, for a measured frame, and for a frame without origin", () => {
    for (const store of [storeWithOrigin(undefined, false), storeWithOrigin("measured"), storeWithOrigin(undefined)]) {
      const { container, unmount } = renderWidget(store);
      expect(container).toBeEmptyDOMElement();
      unmount();
    }
  });

  it("renders nothing, and does not throw, outside a SimulationProvider (no feed store)", () => {
    const { container } = renderWidget(null);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("feature module", () => {
  it("registers one header-actions widget for every role, with no route or nav", () => {
    const registry = createFeatureRegistry([feature], { onReject: () => undefined });
    expect(registry.rejected).toEqual([]);
    expect(registry.allRoutes()).toEqual([]);
    expect(registry.navGroups("viewer")).toEqual([]);
    for (const role of ["viewer", "operator", "admin", null]) {
      expect(registry.slotWidgets("header-actions", role)).toHaveLength(1);
    }
    expect(registry.slotWidgets("dashboard", "viewer")).toHaveLength(0);
  });
});

describe("no demo credentials in this feature's source", () => {
  const files = import.meta.glob("./*.{ts,tsx}", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
  it("contains no account names, passwords or VITE_DEMO variables", () => {
    const sources = Object.entries(files).filter(([path]) => !/\.test\.tsx?$/.test(path));
    expect(sources.length).toBeGreaterThanOrEqual(3);
    for (const [path, src] of sources) {
      expect(src, path).not.toMatch(/demo_(viewer|operator|admin)|VITE_DEMO|password/i);
    }
  });
});
