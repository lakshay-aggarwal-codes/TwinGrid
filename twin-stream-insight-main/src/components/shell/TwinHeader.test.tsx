import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import type { FreshnessState } from "@/telemetry/freshness";
import type { LiveFeed } from "@/three/visualizationModes";
import { feedIn } from "@/three/feedTestUtils";

// Navigation chrome is not under test here.
vi.mock("@/components/transition/RotateLink", () => ({
  RotateLink: ({ to, children }: { to: string; children: ReactNode }) => <a href={to}>{children}</a>,
}));
vi.mock("@/pages/lazyPages.ts", () => ({ loadAnalyticsPage: () => Promise.resolve({}) }));

import { TwinHeader } from "./TwinHeader";

function renderHeader(feed: LiveFeed, extra: { simulationOpen?: boolean } = {}) {
  return render(
    <MemoryRouter>
      <TwinHeader
        onOpenSearch={() => {}}
        feed={feed}
        mode="physical"
        onModeChange={() => {}}
        simulationOpen={extra.simulationOpen ?? false}
        onToggleSimulation={() => {}}
        operationsOpen={false}
        onToggleOperations={() => {}}
        incidentsOpen={false}
        onToggleIncidents={() => {}}
      />
    </MemoryRouter>
  );
}

const status = () => screen.getByTestId("liveness");
const readings = () => screen.getByTestId("live-readings");

describe("TwinHeader liveness + origin (T1a, FE-06)", () => {
  it("shows Live only when the feed is live", () => {
    renderHeader(feedIn("live", { origin: "simulated" }));
    expect(status()).toHaveTextContent("Live");
    expect(status()).toHaveAttribute("data-liveness", "live");
    expect(status().querySelector('[data-freshness="live"]')).not.toBeNull();
  });

  it.each([
    ["stale", "Stale · last update 42 s ago"],
    ["disconnected", "Disconnected · last data 42 s ago"],
    ["reconnecting", "Reconnecting"],
    ["unavailable", "Unavailable"],
  ] as const)("shows %s (with its age where it has one) instead of Live", (state, text) => {
    renderHeader(feedIn(state, { origin: "simulated" }));
    expect(status()).toHaveTextContent(text);
    expect(status()).toHaveAttribute("data-liveness", state);
    expect(status().querySelector('[data-freshness="live"]')).toBeNull();
  });

  it("shows Connecting (no frame yet) instead of Live", () => {
    renderHeader(feedIn("connecting"));
    expect(status()).toHaveTextContent("Connecting");
    expect(status().querySelector('[data-freshness="live"]')).toBeNull();
  });

  it.each(["stale", "disconnected", "reconnecting"] as const)(
    "%s: the last readings are labelled 'Last known' with their age, styled differently, never in the live style",
    (state) => {
      renderHeader(feedIn(state, { origin: "simulated" }));
      expect(screen.getByText("1.23")).toBeInTheDocument();
      expect(readings()).toHaveAttribute("data-readout", "last-known");
      expect(screen.getByTestId("last-known")).toHaveTextContent("Last known · 42 s ago");
      expect(readings().className).toContain("border-dashed");
      expect(readings().className).toContain("text-muted-foreground");
      expect(readings().className).not.toContain("text-foreground");
    }
  );

  it("live: readings are current -- no 'Last known' label and no dashed outline", () => {
    renderHeader(feedIn("live", { origin: "simulated" }));
    expect(readings()).toHaveAttribute("data-readout", "current");
    expect(screen.queryByTestId("last-known")).toBeNull();
    expect(readings().className).not.toContain("border-dashed");
  });

  it.each(["connecting", "unavailable"] as const)("%s: no numbers at all, only '—'", (state) => {
    renderHeader(feedIn(state, state === "unavailable" ? { withFrame: true } : {}));
    expect(readings()).toHaveAttribute("data-readout", "none");
    expect(screen.queryByText("1.23")).toBeNull();
    expect(screen.queryByText("0.456")).toBeNull();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });

  it("renders the data-driven Simulated badge for origin=simulated, with the simulator tooltip", () => {
    renderHeader(feedIn("live", { origin: "simulated" }));
    const banner = screen.getByTestId("origin-banner");
    expect(banner).toHaveTextContent("Simulated");
    expect(banner).toHaveAttribute("data-origin-tone", "simulated");
    expect(banner.querySelector("[data-origin]")!.getAttribute("title")).toMatch(/not measured telemetry/i);
  });

  it("the origin badge stays visible while stale or disconnected", () => {
    for (const state of ["stale", "disconnected"] as FreshnessState[]) {
      const { unmount } = renderHeader(feedIn(state, { origin: "simulated" }));
      expect(screen.getByTestId("origin-banner")).toHaveTextContent("Simulated");
      unmount();
    }
  });

  it.each([null, "", "telemetry", "Measured"])("origin %j is shown as Unverified source (never Measured)", (origin) => {
    renderHeader(feedIn("live", { origin }));
    const banner = screen.getByTestId("origin-banner");
    expect(banner).toHaveTextContent("Unverified source");
    expect(banner).toHaveAttribute("data-origin-tone", "unverified");
    expect(banner).not.toHaveTextContent(/measured/i);
  });

  it("shows the strip context line: Live feed with server time and simulated clock labels", () => {
    renderHeader(feedIn("live", { origin: "simulated" }));
    expect(screen.getByTestId("origin-banner")).toHaveTextContent("Live feed · server time 14:03:21 UTC · simulated clock 2026-01-01 12:35");
  });

  it("shows no origin banner and placeholder readings before any payload", () => {
    renderHeader(feedIn("connecting"));
    expect(screen.queryByTestId("origin-banner")).toBeNull();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });

  it("announces freshness through exactly one status region, with the state only (no age)", () => {
    const { container } = renderHeader(feedIn("stale", { origin: "simulated" }));
    const regions = container.querySelectorAll("header [role='status']");
    expect(regions).toHaveLength(1);
    expect(regions[0]).toHaveTextContent(/^Stale$/);
  });

  it("distinguishes live feed from previews opened from panels", () => {
    const { unmount } = renderHeader(feedIn("live", { origin: "simulated" }));
    expect(screen.queryByTestId("preview-note")).toBeNull();
    unmount();
    renderHeader(feedIn("live", { origin: "simulated" }), { simulationOpen: true });
    expect(screen.getByTestId("preview-note")).toHaveTextContent(/previews, not the live feed/);
  });
});
