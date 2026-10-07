import { afterEach, describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { ApiError } from "@/api/apiError";
import { FALLBACK_LAYOUT } from "./facilityLayout";
import { FALLBACK_BADGE, LOADING_TOPOLOGY, fallbackTopology, getTopology, resetTopology, setTopology, topologyFromQuery, useTopology } from "./facilityTopology.tsx";
import { TopologyBadge } from "./TopologyBadge.tsx";
import { describeRack, nextRackId } from "./rackNavigation.tsx";
import { topologyInput, seedAssets } from "./facilityFixtures";
import type { FacilityTopologyRaw } from "@/api/facility";

type QS = Parameters<typeof topologyFromQuery>[0];
const raw = (assets = seedAssets()): FacilityTopologyRaw => ({ facility: { id: 1, name: "F", frame_unit: "m", frame_note: "note", created_at: "2026-10-02T00:00:00Z" }, assetsFrameUnit: "m", assets });
const ready = (data: FacilityTopologyRaw): QS => ({ status: "ready", data }) as QS;

afterEach(() => resetTopology());

describe("topologyFromQuery", () => {
  it("backend available: backend-sourced layout, no fallback state", () => {
    const t = topologyFromQuery(ready(raw()), false);
    expect(t).toMatchObject({ status: "ready", source: "backend", reason: null, frameUnit: "m", frameNote: "note" });
    expect(t.layout.racks).toHaveLength(36);
    expect(t.layout).not.toBe(FALLBACK_LAYOUT);
  });

  it("loading: the built-in layout is shown but flagged as loading, not as backend-sourced", () => {
    expect(topologyFromQuery({ status: "loading" } as QS, false)).toBe(LOADING_TOPOLOGY);
    expect(LOADING_TOPOLOGY.source).toBe("fallback");
  });

  it.each([
    [new ApiError({ kind: "not_found", status: 404 }).kind, "not_found"],
    ["network", "unavailable"],
    ["server", "unavailable"],
    ["unavailable", "unavailable"],
    ["forbidden", "unavailable"],
    ["contract", "invalid"],
  ] as const)("backend error %s -> fallback (%s)", (kind, reason) => {
    const t = topologyFromQuery({ status: "error", kind } as QS, false);
    expect(t).toMatchObject({ status: "fallback", source: "fallback", reason });
    expect(t.layout).toBe(FALLBACK_LAYOUT);
  });

  it("empty / unauthorized states fall back too", () => {
    expect(topologyFromQuery({ status: "empty" } as QS, false)).toMatchObject({ status: "fallback", reason: "empty" });
    expect(topologyFromQuery({ status: "unauthorized", reason: "session_expired" } as unknown as QS, false)).toMatchObject({ status: "fallback", reason: "unavailable" });
  });

  it("backend data the adapter rejects (count mismatch) falls back with the reason, not a partial scene", () => {
    const t = topologyFromQuery(ready(raw(seedAssets().slice(0, 30))), false);
    expect(t).toMatchObject({ status: "fallback", reason: "count_mismatch" });
    expect(t.layout).toBe(FALLBACK_LAYOUT);
  });

  it("VITE_TOPOLOGY_SOURCE=static: built-in layout, flagged, whatever the query says", () => {
    expect(topologyFromQuery(ready(raw()), true)).toMatchObject({ status: "fallback", reason: "configured_static" });
  });

  it("unplaced assets are carried on the topology", () => {
    const t = topologyFromQuery(
      ready(raw([...seedAssets(), { id: 99, external_id: "spare", name: "s", asset_type: "rack", retired_at: null, pose: null, located_in: null }])),
      false,
    );
    expect(t.unplaced).toHaveLength(1);
  });
});

describe("TopologyBadge", () => {
  it("is absent when the backend topology is in use (acceptance)", () => {
    const { container } = render(<TopologyBadge topology={topologyFromQuery(ready(raw()), false)} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("is visible as DOM text for every fallback reason, with the reason stated", () => {
    for (const reason of ["unavailable", "not_found", "empty", "count_mismatch", "unsupported_frame_unit", "invalid", "configured_static"] as const) {
      const { unmount } = render(<TopologyBadge topology={fallbackTopology(reason)} />);
      const badge = screen.getByTestId("topology-badge");
      expect(badge).toHaveAttribute("role", "status");
      expect(badge).toHaveTextContent(FALLBACK_BADGE);
      expect(badge.textContent!.length).toBeGreaterThan(FALLBACK_BADGE.length + 10);
      unmount();
    }
  });

  it("shows a loading state distinct from fallback", () => {
    render(<TopologyBadge topology={LOADING_TOPOLOGY} />);
    expect(screen.getByTestId("topology-badge")).toHaveAttribute("data-topology", "loading");
    expect(screen.getByTestId("topology-badge")).not.toHaveTextContent("built-in fallback");
  });
});

describe("the active topology store", () => {
  function Probe() {
    return <span data-testid="probe">{useTopology().status}</span>;
  }

  it("publishes changes to subscribers and to non-React readers", () => {
    render(<Probe />);
    expect(screen.getByTestId("probe")).toHaveTextContent("loading");
    act(() => setTopology(topologyFromQuery(ready(raw()), false)));
    expect(screen.getByTestId("probe")).toHaveTextContent("ready");
    expect(getTopology().source).toBe("backend");
  });
});

describe("keyboard navigation over backend ids", () => {
  it("traverses a backend layout whose ids differ from the built-in ones (nothing hard-coded to the fallback)", () => {
    const renamed = seedAssets().map((a) => (a.asset_type === "rack" ? { ...a, external_id: `B-${a.external_id}` } : a));
    const t = topologyFromQuery(ready(raw(renamed)), false);
    expect(t.status).toBe("ready");
    const L = t.layout;
    expect(nextRackId(null, "ArrowRight", L)).toBe("B-zone-1-row-1-rack-1");
    expect(nextRackId("B-zone-1-row-1-rack-1", "ArrowRight", L)).toBe("B-zone-1-row-1-rack-2");
    expect(nextRackId("B-zone-1-row-1-rack-6", "ArrowRight", L)).toBe("B-zone-2-row-1-rack-1");
    expect(nextRackId("B-zone-2-row-1-rack-3", "ArrowDown", L)).toBe("B-zone-2-row-2-rack-3");
    expect(nextRackId("B-zone-1-row-1-rack-1", "End", L)).toBe("B-zone-3-row-2-rack-6");
    expect(describeRack("B-zone-1-row-2-rack-3", L)).toBe("Zone A, row 2, rack 3");
  });

  it("the non-React helpers follow the ACTIVE topology by default", () => {
    const renamed = seedAssets().map((a) => (a.asset_type === "rack" ? { ...a, external_id: `X-${a.external_id}` } : a));
    act(() => setTopology(topologyFromQuery(ready(raw(renamed)), false)));
    expect(nextRackId(null, "Home")).toBe("X-zone-1-row-1-rack-1");
    act(() => resetTopology());
    expect(nextRackId(null, "Home")).toBe("zone-1-row-1-rack-1");
  });

  it("an asset id with no row in its name still describes and traverses (zone-ordered)", () => {
    const plain = seedAssets().map((a, i) => (a.asset_type === "rack" ? { ...a, external_id: `R${String(i).padStart(3, "0")}` } : a));
    const t = topologyFromQuery(ready(raw(plain)), false);
    expect(t.status).toBe("ready");
    const first = t.layout.racks[0].rackId;
    expect(describeRack(first, t.layout)).toBe(`Zone A, ${first}`);
  });
});

void topologyInput;
