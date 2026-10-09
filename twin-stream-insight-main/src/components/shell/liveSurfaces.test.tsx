/** FE-06: every Live Twin surface across live / stale / disconnected / reconnecting / unavailable / connecting. */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type { FreshnessState } from "@/telemetry/freshness";
import { feedIn } from "@/three/feedTestUtils.ts";
import { FeedOverlay, ModeLegend } from "./ModeLegend";
import { ThermalLegend } from "./ThermalLegend";
import { RackInspectorContent } from "./RackInspectorContent";
import { SidePanel } from "./SidePanel";

const LAST_KNOWN_STATES = ["stale", "disconnected", "reconnecting"] as const;
const NO_NUMBER_STATES = ["connecting", "unavailable"] as const;
const noop = () => {};

describe("ModeLegend", () => {
  it("live: current values in the normal style, with the origin + freshness badge", () => {
    const { container } = render(<ModeLegend mode="energy" feed={feedIn("live")} onGenerateReport={noop} />);
    expect(screen.getByTestId("mode-legend")).toHaveAttribute("data-readout", "current");
    expect(screen.getByText("1.23")).toBeInTheDocument();
    expect(container.querySelector("[data-value='current']")).not.toBeNull();
    expect(screen.queryByTestId("last-known")).toBeNull();
    expect(container.querySelector("[data-freshness='live']")).not.toBeNull();
    expect(container.querySelector("[data-origin='simulated']")).not.toBeNull();
  });

  it.each(LAST_KNOWN_STATES)("%s: values are 'Last known' with their age, muted and dashed, never current", (state) => {
    const { container } = render(<ModeLegend mode="energy" feed={feedIn(state)} onGenerateReport={noop} />);
    expect(screen.getByTestId("mode-legend")).toHaveAttribute("data-readout", "last-known");
    expect(screen.getByTestId("mode-legend").className).toContain("border-dashed");
    expect(screen.getByTestId("last-known")).toHaveTextContent("Last known · 42 s ago");
    expect(container.querySelector("[data-value='current']")).toBeNull();
    expect(container.querySelector("[data-value='last-known']")).not.toBeNull();
    expect(container.querySelector("[data-freshness='live']")).toBeNull();
  });

  it.each(NO_NUMBER_STATES)("%s: no numbers; an explicit state notice instead", (state) => {
    const { container } = render(<ModeLegend mode="energy" feed={feedIn(state)} onGenerateReport={noop} />);
    expect(screen.getByTestId("mode-legend")).toHaveAttribute("data-readout", "none");
    expect(screen.queryByText("1.23")).toBeNull();
    expect(container.querySelector("[data-state]")).not.toBeNull();
  });

  it("the sustainability report is offered only from current data", () => {
    const { unmount } = render(<ModeLegend mode="sustainability" feed={feedIn("live")} onGenerateReport={noop} />);
    expect(screen.getByRole("button", { name: /Generate sustainability report/ })).toBeInTheDocument();
    unmount();
    for (const s of [...LAST_KNOWN_STATES, ...NO_NUMBER_STATES] as FreshnessState[]) {
      const r = render(<ModeLegend mode="sustainability" feed={feedIn(s)} onGenerateReport={noop} />);
      expect(screen.queryByRole("button", { name: /Generate sustainability report/ })).toBeNull();
      r.unmount();
    }
  });

  it("physical mode renders no legend", () => {
    const { container } = render(<ModeLegend mode="physical" feed={feedIn("live")} onGenerateReport={noop} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("the carbon fallback caveat shows for last-known values too, never hidden", () => {
    render(<ModeLegend mode="sustainability" feed={feedIn("stale", { state: { carbon_data_is_real: false } })} onGenerateReport={noop} />);
    expect(screen.getByText(/flat fallback figure/)).toBeInTheDocument();
  });
});

describe("ThermalLegend", () => {
  it("live: current inlet/outlet readings", () => {
    const { container } = render(<ThermalLegend feed={feedIn("live")} />);
    expect(screen.getByTestId("thermal-legend")).toHaveAttribute("data-readout", "current");
    expect(screen.getByText("20.0°C")).toBeInTheDocument();
    expect(container.querySelector("[data-thermal-value='current']")).not.toBeNull();
  });

  it.each(LAST_KNOWN_STATES)("%s: readings are last known with age; the scene-neutral note is shown", (state) => {
    const { container } = render(<ThermalLegend feed={feedIn(state)} />);
    expect(screen.getByTestId("thermal-legend")).toHaveAttribute("data-readout", "last-known");
    expect(screen.getByTestId("last-known")).toHaveTextContent(/Last known · 42 s ago/);
    expect(container.querySelector("[data-thermal-value='current']")).toBeNull();
    expect(container.querySelectorAll("[data-thermal-value='last-known']")).toHaveLength(2);
    expect(screen.getByTestId("thermal-legend").className).toContain("border-dashed");
  });

  it.each(NO_NUMBER_STATES)("%s: no temperatures, a state notice instead", (state) => {
    render(<ThermalLegend feed={feedIn(state)} />);
    expect(screen.getByTestId("thermal-legend")).toHaveAttribute("data-readout", "none");
    expect(screen.queryByText(/°C$/)).toBeNull();
  });
});

describe("RackInspectorContent facility reference", () => {
  const RACK = "zone-2-row-1-rack-3";

  it("live: current values, labelled facility-wide and live", () => {
    render(<RackInspectorContent rackId={RACK} feed={feedIn("live")} />);
    expect(screen.getByTestId("facility-reference")).toHaveAttribute("data-readout", "current");
    expect(screen.getByText(/Facility-wide, live/)).toBeInTheDocument();
    expect(screen.getByText("1.23")).toBeInTheDocument();
  });

  it.each(LAST_KNOWN_STATES)("%s: last known with age; no per-rack inference is added", (state) => {
    render(<RackInspectorContent rackId={RACK} feed={feedIn(state)} />);
    expect(screen.getByTestId("facility-reference")).toHaveAttribute("data-readout", "last-known");
    expect(screen.getByTestId("last-known")).toHaveTextContent("Last known · 42 s ago");
    expect(screen.getByText(/Facility-wide, last known/)).toBeInTheDocument();
    expect(screen.queryByText(/Facility-wide, live/)).toBeNull();
    expect(screen.getByText(/Per-rack telemetry not yet available/)).toBeInTheDocument();
  });

  it.each([...NO_NUMBER_STATES, "absent"] as const)("%s: no numbers", (state) => {
    render(<RackInspectorContent rackId={RACK} feed={state === "absent" ? undefined : feedIn(state)} />);
    expect(screen.queryByTestId("facility-reference")).toBeNull();
    expect(screen.queryByText("1.23")).toBeNull();
  });

  it("SidePanel passes the feed through to the inspector", () => {
    render(<SidePanel selectedRackId={RACK} onDeselect={noop} feed={feedIn("stale")} />);
    expect(screen.getByTestId("facility-reference")).toHaveAttribute("data-readout", "last-known");
  });
});

describe("FeedOverlay", () => {
  it("renders nothing while live", () => {
    const { container } = render(<FeedOverlay feed={feedIn("live")} />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    ["stale", "Stale · last update 42 s ago"],
    ["disconnected", "Disconnected · last data 42 s ago"],
    ["reconnecting", "Reconnecting (attempt 2)"],
    ["unavailable", "Unavailable"],
    ["connecting", "Connecting"],
  ] as const)("%s: states why the scene is neutral, with the age where it has one", (state, text) => {
    render(<FeedOverlay feed={feedIn(state, { attempt: 2 })} />);
    const overlay = screen.getByTestId("feed-overlay");
    expect(overlay).toHaveAttribute("data-feed-state", state);
    expect(overlay).toHaveTextContent(text);
    expect(overlay).toHaveTextContent("Scene colours are neutral");
    expect(overlay.querySelector("[aria-live],[role='status'],[role='alert']")).toBeNull();
  });
});
