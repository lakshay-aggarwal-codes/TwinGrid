import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { createFeedStore } from "@/telemetry/feedStore";
import { clearActiveFeed, setActiveFeed } from "@/telemetry/activeFeed";
import { fakeClock, fakeTransport, liveFrame } from "@/telemetry/testUtils";
import { StatusBar } from "./StatusBar";
import feature from "./index";

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function setup() {
  const clock = fakeClock();
  const t = fakeTransport();
  const store = createFeedStore({ connect: t.connect, clock, checkIntervalMs: 1000 });
  store.start();
  setActiveFeed(store);
  const utils = render(<StatusBar clock={clock} />);
  const cleanupFeed = () => {
    clearActiveFeed(store);
    store.stop();
  };
  return { clock, t, store, cleanupFeed, ...utils };
}

describe("persistent status bar", () => {
  it("renders nothing while signed out (no feed)", () => {
    render(<StatusBar />);
    expect(screen.queryByTestId("status-bar")).toBeNull();
  });

  it("shows connecting, no data yet, and an origin it has not seen", () => {
    const s = setup();
    expect(screen.getByRole("group", { name: "Connection status" })).toBeInTheDocument();
    expect(screen.getByTestId("status-connection")).toHaveTextContent("Connecting");
    expect(screen.getByTestId("status-age")).toHaveTextContent("No data received yet");
    expect(screen.getByTestId("status-origin")).toHaveTextContent("not reported yet");
    s.cleanupFeed();
  });

  it("shows Live, the data origin the backend declared, and a ticking age", () => {
    const s = setup();
    act(() => {
      s.t.h.onStatus?.("open");
      s.t.h.onMessage?.(liveFrame({ origin: "simulated" }));
    });
    expect(screen.getByTestId("status-connection")).toHaveTextContent("Live");
    expect(screen.getByTestId("status-origin")).toHaveTextContent("Data origin: Simulated");
    expect(screen.getByTestId("status-origin")).toHaveAttribute("data-origin", "simulated");
    expect(screen.getByTestId("status-age")).toHaveTextContent("Last update: 0 s ago");
    act(() => {
      s.clock.advance(2000);
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByTestId("status-age")).toHaveTextContent("Last update: 2 s ago");
    s.cleanupFeed();
  });

  it("never shows a missing origin as simulated", () => {
    const s = setup();
    act(() => {
      s.t.h.onStatus?.("open");
      s.t.h.onMessage?.(liveFrame());
    });
    expect(screen.getByTestId("status-origin")).toHaveTextContent("Unverified source");
    s.cleanupFeed();
  });

  it("shows Disconnected with an assertive announcement, and a text cue, when the socket closes", () => {
    const s = setup();
    act(() => {
      s.t.h.onStatus?.("open");
      s.t.h.onMessage?.(liveFrame({ origin: "simulated" }));
    });
    act(() => {
      s.t.h.onStatus?.("closed");
    });
    expect(screen.getByTestId("status-connection")).toHaveTextContent("Disconnected");
    const live = screen.getByTestId("status-announcement");
    expect(live).toHaveAttribute("role", "status");
    expect(live).toHaveAttribute("aria-live", "assertive");
    expect(live).toHaveTextContent("Connection: Disconnected");
    s.cleanupFeed();
  });

  it("announces ordinary states politely", () => {
    const s = setup();
    expect(screen.getByTestId("status-announcement")).toHaveAttribute("aria-live", "polite");
    s.cleanupFeed();
  });

  it("disappears when the feed is cleared (sign-out)", () => {
    const s = setup();
    act(() => {
      s.cleanupFeed();
    });
    expect(screen.queryByTestId("status-bar")).toBeNull();
  });

  it("is a settings-slot feature", () => {
    expect(feature.id).toBe("app-states");
    expect(feature.slots?.map((x) => x.slot)).toEqual(["settings"]);
  });
});
