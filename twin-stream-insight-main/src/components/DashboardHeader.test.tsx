import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { feedIn } from "@/three/feedTestUtils";
import type { LiveFeed } from "@/three/visualizationModes";

vi.mock("@/components/transition/RotateLink", () => ({
  RotateLink: ({ to, children }: { to: string; children: ReactNode }) => <a href={to}>{children}</a>,
}));

import { DashboardHeader } from "./DashboardHeader.tsx";

const renderHeader = (feed: LiveFeed) => render(<DashboardHeader feed={feed} />);
afterEach(() => vi.restoreAllMocks());

describe("DashboardHeader (FE-08)", () => {
  it("no longer claims 'Systems Online' and has no static SIMULATED banner", () => {
    renderHeader(feedIn("live"));
    expect(screen.queryByText(/Systems Online/i)).toBeNull();
    expect(screen.queryByTestId("simulated-banner")).toBeNull();
    expect(screen.queryByText(/no measured telemetry/i)).toBeNull();
  });

  it("shows no browser clock: no ticking timer is started", () => {
    const spy = vi.spyOn(globalThis, "setInterval");
    renderHeader(feedIn("live"));
    expect(spy).not.toHaveBeenCalled();
  });

  it("live: origin and freshness come from the feed (Simulated + Live)", () => {
    const { container } = renderHeader(feedIn("live", { origin: "simulated" }));
    expect(screen.getByTestId("liveness")).toHaveAttribute("data-liveness", "live");
    expect(container.querySelector("[data-origin='simulated']")).not.toBeNull();
    expect(container.querySelector("[data-freshness='live']")).not.toBeNull();
    expect(screen.getByTestId("origin-banner")).toBeTruthy();
  });

  it("stale feed: the header says Stale with its age and nothing says live", () => {
    const { container } = renderHeader(feedIn("stale", { ageMs: 42_000 }));
    expect(screen.getByTestId("liveness")).toHaveAttribute("data-liveness", "stale");
    const chip = container.querySelector("[data-freshness='stale']");
    expect(chip).not.toBeNull();
    expect(chip).toHaveTextContent(/Stale/);
    expect(chip).toHaveTextContent(/42 s/);
    expect(container.querySelector("[data-freshness='live']")).toBeNull();
  });

  it.each(["disconnected", "reconnecting"] as const)("%s: shown as such, never live", (state) => {
    const { container } = renderHeader(feedIn(state, { attempt: 2 }));
    expect(container.querySelector(`[data-freshness='${state}']`)).not.toBeNull();
    expect(container.querySelector("[data-freshness='live']")).toBeNull();
  });

  it("origin absent: 'Unverified source', never Simulated or Measured", () => {
    const { container } = renderHeader(feedIn("live", { origin: null }));
    expect(container.querySelector("[data-origin='unverified']")).not.toBeNull();
    expect(container.querySelector("[data-origin='simulated']")).toBeNull();
    expect(container.querySelector("[data-origin='measured']")).toBeNull();
  });

  it("no frame yet (connecting): just the freshness chip; no origin is guessed", () => {
    const { container } = renderHeader(feedIn("connecting"));
    expect(container.querySelector("[data-freshness='connecting']")).not.toBeNull();
    expect(screen.queryByTestId("origin-banner")).toBeNull();
    expect(container.querySelector("[data-origin]")).toBeNull();
  });

  it("mounts exactly one live region for freshness transitions", () => {
    const { container } = renderHeader(feedIn("stale"));
    expect(container.querySelectorAll("[data-freshness-announcement]")).toHaveLength(1);
  });

  it("keeps the link back to the Live Twin", () => {
    renderHeader(feedIn("live"));
    expect(screen.getByRole("link", { name: /Live Twin/ })).toHaveAttribute("href", "/");
  });
});
