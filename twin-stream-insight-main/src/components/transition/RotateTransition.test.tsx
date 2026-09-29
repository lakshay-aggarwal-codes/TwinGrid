import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

// GSAP is replaced by a synchronous stand-in that "finishes" immediately, so
// the tests exercise OUR sequencing (leave -> preload -> navigate -> arrive ->
// focus heading), not GSAP's clock.
const gsapMock = vi.hoisted(() => {
  const kill = vi.fn();
  return {
    set: vi.fn(),
    to: vi.fn((_el: unknown, vars: { onComplete?: () => void }) => {
      vars.onComplete?.();
      return { kill };
    }),
    fromTo: vi.fn((_el: unknown, _from: unknown, to: { onComplete?: () => void }) => {
      to.onComplete?.();
      return { kill };
    }),
  };
});
vi.mock("gsap", () => ({ default: gsapMock }));

const motion = vi.hoisted(() => ({ duration: 0.38 }));
vi.mock("@/three/motion", () => ({
  MOTION: { pageRotate: 0.38 },
  motionDuration: (s: number) => (motion.duration === 0 ? 0 : s),
}));

// The real loader would import the whole Analytics page (recharts and all).
// Tests control when the "chunk download" finishes.
const loader = vi.hoisted(() => ({
  load: (() => Promise.resolve({})) as () => Promise<unknown>,
}));
vi.mock("@/pages/lazyPages", () => ({ loadAnalyticsPage: () => loader.load() }));

import { RotateTransition } from "./RotateTransition";
import { RotateLink } from "./RotateLink";

const STORAGE_KEY = "twingrid.transition";

function renderApp() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <RotateTransition>
        <Routes>
          <Route
            path="/"
            element={
              <div>
                <h1>Home page</h1>
                <RotateLink to="/b" direction={1}>
                  go b
                </RotateLink>
              </div>
            }
          />
          <Route
            path="/b"
            element={
              <div>
                <h1>Page B</h1>
                <RotateLink to="/" direction={-1}>
                  go home
                </RotateLink>
              </div>
            }
          />
        </Routes>
      </RotateTransition>
    </MemoryRouter>,
  );
}

const pageB = () => screen.findByRole("heading", { name: "Page B" });

describe("RotateTransition", () => {
  beforeEach(() => {
    motion.duration = 0.38;
    loader.load = () => Promise.resolve({});
    localStorage.clear();
    gsapMock.set.mockClear();
    gsapMock.to.mockClear();
    gsapMock.fromTo.mockClear();
  });

  it("does not steal focus or animate an out-swing on first load", () => {
    renderApp();
    expect(gsapMock.to).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(document.body);
  });

  it("defaults to a crossfade (opacity only, no rotation)", async () => {
    renderApp();
    fireEvent.click(screen.getByText("go b"));
    await pageB();

    const out = gsapMock.to.mock.calls[0][1] as Record<string, unknown>;
    expect(out).toMatchObject({ opacity: 0 });
    expect(out).not.toHaveProperty("rotationY");
    const arrival = gsapMock.fromTo.mock.calls.at(-1)!;
    expect(arrival[1]).toMatchObject({ opacity: 0 });
    expect(arrival[2]).toMatchObject({ opacity: 1, clearProps: "transform,opacity,clipPath,filter" });
  });

  describe("door swing (rotate) style", () => {
    beforeEach(() => localStorage.setItem(STORAGE_KEY, "rotate"));

    it("swings out one way, navigates, swings in from the other side, then focuses the new heading", async () => {
      renderApp();
      fireEvent.click(screen.getByText("go b"));

      expect(gsapMock.to).toHaveBeenCalledTimes(1);
      expect(gsapMock.to.mock.calls[0][1]).toMatchObject({ rotationY: 90 });
      const heading = await pageB();

      const arrival = gsapMock.fromTo.mock.calls.at(-1)!;
      expect(arrival[1]).toMatchObject({ rotationY: -90 });
      expect(arrival[2]).toMatchObject({ rotationY: 0 });
      expect(document.activeElement).toBe(heading);
    });

    it("rotates the opposite way when coming back", async () => {
      renderApp();
      fireEvent.click(screen.getByText("go b"));
      await pageB();
      gsapMock.to.mockClear();
      fireEvent.click(screen.getByText("go home"));

      expect(gsapMock.to.mock.calls[0][1]).toMatchObject({ rotationY: -90 });
      await screen.findByRole("heading", { name: "Home page" });
      expect(gsapMock.fromTo.mock.calls.at(-1)![1]).toMatchObject({ rotationY: 90 });
    });
  });

  it("holds the page until the next chunk has downloaded, when that happens within the time limit", async () => {
    let finishDownload!: () => void;
    loader.load = () => new Promise((resolve) => (finishDownload = () => resolve({})));
    renderApp();
    fireEvent.click(screen.getByText("go b"));

    // The leave animation is already done (mock is instant), but navigation waits.
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.queryByRole("heading", { name: "Page B" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Home page" })).toBeTruthy();

    await act(async () => finishDownload());
    await pageB();
  });

  it("stops waiting after 1.5 s so the Loading fallback can show instead of a blank screen", async () => {
    vi.useFakeTimers();
    try {
      loader.load = () => new Promise(() => {}); // a download that never finishes
      renderApp();
      fireEvent.click(screen.getByText("go b"));

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1400);
      });
      expect(screen.queryByRole("heading", { name: "Page B" })).toBeNull();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(200);
      });
      expect(screen.getByRole("heading", { name: "Page B" })).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it("still navigates if the chunk fails to download", async () => {
    loader.load = () => Promise.reject(new Error("offline"));
    renderApp();
    fireEvent.click(screen.getByText("go b"));
    await pageB();
  });

  it("navigates instantly, with no animation, under reduced motion - and still moves focus", async () => {
    motion.duration = 0;
    renderApp();
    fireEvent.click(screen.getByText("go b"));

    expect(gsapMock.to).not.toHaveBeenCalled();
    expect(gsapMock.fromTo).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(await pageB());
  });

  it('the "none" style is instant too', async () => {
    localStorage.setItem(STORAGE_KEY, "none");
    renderApp();
    fireEvent.click(screen.getByText("go b"));

    expect(gsapMock.to).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(await pageB());
  });

  it("switching style in the picker changes the next transition and is remembered", async () => {
    renderApp();
    fireEvent.change(screen.getByLabelText("Page transition style"), { target: { value: "rotate" } });
    expect(localStorage.getItem(STORAGE_KEY)).toBe("rotate");

    fireEvent.click(screen.getByText("go b"));
    expect(gsapMock.to.mock.calls[0][1]).toMatchObject({ rotationY: 90 });
    await pageB();
  });

  it("ignores an unknown stored style and falls back to the default", async () => {
    localStorage.setItem(STORAGE_KEY, "spin-me-round");
    renderApp();
    fireEvent.click(screen.getByText("go b"));
    expect(gsapMock.to.mock.calls[0][1]).toMatchObject({ opacity: 0 });
    await pageB();
  });

  it("leaves modified clicks (ctrl/cmd/middle) to the browser", () => {
    renderApp();
    // jsdom cannot perform a real navigation; swallow the browser default so
    // the test output stays clean. We only assert that OUR animation did not run.
    const swallow = (e: Event) => e.preventDefault();
    document.addEventListener("click", swallow);
    fireEvent.click(screen.getByText("go b"), { ctrlKey: true });
    expect(gsapMock.to).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("go b"), { button: 1 });
    expect(gsapMock.to).not.toHaveBeenCalled();
    document.removeEventListener("click", swallow);
  });

  it("throws a clear error when RotateLink is used outside the transition", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() =>
      render(
        <MemoryRouter>
          <RotateLink to="/x">x</RotateLink>
        </MemoryRouter>,
      ),
    ).toThrow(/RotateTransition/);
    spy.mockRestore();
  });
});
