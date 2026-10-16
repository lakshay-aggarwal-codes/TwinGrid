import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { createFeedStore } from "@/telemetry/feedStore";
import { clearActiveFeed, setActiveFeed } from "@/telemetry/activeFeed";
import { fakeClock, fakeTransport } from "@/telemetry/testUtils";
import { StatusBar } from "../app-states/StatusBar";
import { IDLE, type BackfillState, type Backfiller } from "./backfill";
import { useBackfillState } from "./backfillState";
import feature from "./index";

const created: FakeBackfiller[] = [];

class FakeBackfiller implements Backfiller {
  state: BackfillState = IDLE;
  started = 0;
  stopped = 0;
  private listeners = new Set<() => void>();
  start() {
    this.started += 1;
  }
  stop() {
    this.stopped += 1;
  }
  getState() {
    return this.state;
  }
  subscribe(l: () => void) {
    this.listeners.add(l);
    return () => void this.listeners.delete(l);
  }
  push(next: BackfillState) {
    this.state = next;
    this.listeners.forEach((l) => l());
  }
}

vi.mock("./backfill", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./backfill")>()),
  createBackfiller: () => {
    const b = new FakeBackfiller();
    created.push(b);
    return b;
  },
}));

import BackfillHost from "./BackfillHost";

const gap = { from: "2026-01-01T12:00:00.001Z", to: "2026-01-01T12:00:12.000Z", missedFrames: 3, truncated: false };

function Probe() {
  return <span data-testid="probe">{useBackfillState().status}</span>;
}

beforeEach(() => {
  vi.useFakeTimers();
  created.length = 0;
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function feed() {
  const store = createFeedStore({ connect: fakeTransport().connect, clock: fakeClock() });
  store.start();
  return store;
}

describe("BackfillHost", () => {
  it("is registered as a settings-slot widget of the realtime-resilience feature", () => {
    expect(feature.id).toBe("realtime-resilience");
    expect(feature.slots?.map((s) => s.slot)).toEqual(["settings"]);
  });

  it("does nothing while signed out (no feed)", () => {
    render(<BackfillHost context={{}} />);
    expect(created).toHaveLength(0);
  });

  it("runs one backfiller per feed, publishes its state, and stops it on unmount", () => {
    const store = feed();
    setActiveFeed(store);
    const { unmount } = render(
      <>
        <BackfillHost context={{}} />
        <Probe />
      </>
    );
    expect(created).toHaveLength(1);
    expect(created[0].started).toBe(1);
    expect(screen.getByTestId("probe")).toHaveTextContent("idle");
    act(() => created[0].push({ status: "loading", window: gap }));
    expect(screen.getByTestId("probe")).toHaveTextContent("loading");
    unmount();
    expect(created[0].stopped).toBe(1);
    clearActiveFeed(store);
    store.stop();
  });
});

describe("status bar backfill line", () => {
  it("is absent normally and shows loading, then the honest result, as the backfiller reports", () => {
    const store = feed();
    setActiveFeed(store);
    render(
      <>
        <BackfillHost context={{}} />
        <StatusBar clock={fakeClock()} />
      </>
    );
    expect(screen.queryByTestId("status-backfill")).toBeNull();
    act(() => created[0].push({ status: "loading", window: gap }));
    expect(screen.getByTestId("status-backfill")).toHaveTextContent("Backfilling 3 missed updates…");
    act(() => created[0].push({ status: "done", window: gap, series: [], recovered: 2, moreAvailable: false }));
    expect(screen.getByTestId("status-backfill")).toHaveAttribute("data-state", "done");
    expect(screen.getByTestId("status-backfill")).toHaveTextContent("Backfilled 2 of 3 missed updates (the rest were not stored)");
    act(() => created[0].push({ status: "unavailable", window: gap }));
    expect(screen.getByTestId("status-backfill")).toHaveTextContent("stored history unavailable");
    act(() => created[0].push(IDLE));
    expect(screen.queryByTestId("status-backfill")).toBeNull();
    clearActiveFeed(store);
    store.stop();
  });
});
