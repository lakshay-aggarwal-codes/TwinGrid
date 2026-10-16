import "@/test/resizeObserver";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { createFeatureRegistry } from "../registry";
import type { FeatureModule } from "../types";
import type { TourStep } from "./engine";
import feature from "./index";
import { requestTour } from "./requests";
import { TOUR_STORAGE_KEY } from "./storage";
import { TourHost } from "./TourHost";

let currentRole: string | null = "operator";
vi.mock("@/hooks/useAuth.ts", () => ({ useRole: () => ({ role: currentRole }) }));

const page = (id: string, path: string): FeatureModule => ({ id, route: { path, component: () => null } });
const registry = createFeatureRegistry([page("p2", "/p2"), page("p3", "/p3")], { onReject: () => undefined });

const step = (id: string, route: string, extra: Partial<TourStep> = {}): TourStep => ({ id, route, title: `Title ${id}`, caption: `Caption ${id}`, durationMs: 1000, ...extra });
const STEPS = [step("one", "/"), step("two", "/p2"), step("op-only", "/p2", { minRole: "operator" }), step("gone", "/not-registered"), step("last", "/p3")];

const Where = () => <span data-testid="where">{useLocation().pathname}</span>;
const Leave = () => {
  const nav = useNavigate();
  return (
    <button type="button" onClick={() => nav("/analytics")}>
      leave by hand
    </button>
  );
};

const stored = () => JSON.parse(window.localStorage.getItem(TOUR_STORAGE_KEY) ?? "null");
const tick = (ms: number) => act(() => void vi.advanceTimersByTime(ms));
const card = () => screen.queryByRole("dialog", { name: "Story mode" });

function mount(props: { steps?: readonly TourStep[] } = {}) {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <TourHost steps={props.steps ?? STEPS} registry={registry} tickMs={500} />
      <Where />
      <Leave />
    </MemoryRouter>,
  );
}

const seenPrefs = () => window.localStorage.setItem(TOUR_STORAGE_KEY, JSON.stringify({ welcomeSeen: true, resumeStepId: null, completed: false }));

beforeEach(() => {
  vi.useFakeTimers();
  currentRole = "operator";
  window.localStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("first-run welcome", () => {
  it("shows once, and 'Explore on my own' dismisses it for good", () => {
    const { unmount } = mount();
    expect(screen.getByRole("dialog", { name: "Welcome to TwinGrid" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Explore on my own" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(stored()).toMatchObject({ welcomeSeen: true });
    unmount();
    mount();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("tells a viewer the tour is read-only and an operator about their actions", () => {
    currentRole = "viewer";
    const { unmount } = mount();
    expect(screen.getByText(/signed in as a viewer/i)).toBeInTheDocument();
    unmount();
    cleanup();
    window.localStorage.clear();
    currentRole = "operator";
    mount();
    expect(screen.getByText(/signed in as an operator/i)).toBeInTheDocument();
  });

  it("Escape closes it without starting the tour", () => {
    mount();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(card()).toBeNull();
    expect(stored()).toMatchObject({ welcomeSeen: true });
  });

  it("'Start Story Mode' begins at the first step", () => {
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Start Story Mode" }));
    expect(card()).toBeInTheDocument();
    expect(screen.getByText("Title one")).toBeInTheDocument();
    expect(screen.getByText(/step 1 of 4/i)).toBeInTheDocument();
  });
});

describe("story mode", () => {
  beforeEach(seenPrefs);

  it("does not appear until asked, then follows the steps by itself, navigating between pages", () => {
    mount();
    expect(card()).toBeNull();
    act(() => requestTour("start"));
    expect(screen.getByText("Title one")).toBeInTheDocument();
    tick(1000);
    expect(screen.getByText("Title two")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/p2");
    tick(1000);
    expect(screen.getByText("Title op-only")).toBeInTheDocument();
    tick(1000);
    expect(screen.getByText("Title last")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/p3");
  });

  it("leaves out steps whose page does not exist", () => {
    mount();
    act(() => requestTour("start"));
    expect(screen.getByText(/step 1 of 4/i)).toBeInTheDocument(); // five steps, one unregistered
  });

  it("shows a viewer only what a viewer can use", () => {
    currentRole = "viewer";
    mount();
    act(() => requestTour("start"));
    expect(screen.getByText(/step 1 of 3/i)).toBeInTheDocument();
    tick(2000);
    expect(screen.queryByText("Title op-only")).toBeNull();
    expect(screen.getByText("Title last")).toBeInTheDocument();
  });

  it("pauses and resumes on the control, and does not advance while paused", () => {
    mount();
    act(() => requestTour("start"));
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(screen.getByText(/Paused/)).toBeInTheDocument();
    tick(10_000);
    expect(screen.getByText("Title one")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    tick(1000);
    expect(screen.getByText("Title two")).toBeInTheDocument();
  });

  it("is keyboard controllable: arrows step, P pauses", () => {
    mount();
    act(() => requestTour("start"));
    fireEvent.keyDown(document.body, { key: "ArrowRight" });
    expect(screen.getByText("Title two")).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "ArrowLeft" });
    expect(screen.getByText("Title one")).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "p" });
    expect(screen.getByRole("button", { name: "Resume" })).toBeInTheDocument();
  });

  it("leaves typing alone: arrow keys in a text field do not step the tour", () => {
    mount();
    act(() => requestTour("start"));
    const input = document.createElement("input");
    document.body.appendChild(input);
    fireEvent.keyDown(input, { key: "ArrowRight" });
    expect(screen.getByText("Title one")).toBeInTheDocument();
    input.remove();
  });

  it("Back is disabled on the first step and the last step says Finish", () => {
    mount();
    act(() => requestTour("start"));
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("button", { name: "Finish" })).toBeInTheDocument();
  });

  it("Skip (button or Escape) ends it and remembers the step; resume continues from there", () => {
    mount();
    act(() => requestTour("start"));
    tick(1000);
    fireEvent.click(screen.getAllByRole("button", { name: "Skip tour" })[0]);
    expect(card()).toBeNull();
    expect(stored()).toMatchObject({ resumeStepId: "two" });

    act(() => requestTour("resume"));
    expect(screen.getByText("Title two")).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(card()).toBeNull();
    expect(stored()).toMatchObject({ resumeStepId: "two" });
  });

  it("starts from the beginning when asked to resume with nothing to resume", () => {
    mount();
    act(() => requestTour("resume"));
    expect(screen.getByText("Title one")).toBeInTheDocument();
  });

  it("'start' always begins at the first step, even with a resume point", () => {
    window.localStorage.setItem(TOUR_STORAGE_KEY, JSON.stringify({ welcomeSeen: true, resumeStepId: "last", completed: false }));
    mount();
    act(() => requestTour("start"));
    expect(screen.getByText("Title one")).toBeInTheDocument();
  });

  it("the welcome offers 'Resume where I stopped' when there is a resume point", () => {
    window.localStorage.setItem(TOUR_STORAGE_KEY, JSON.stringify({ welcomeSeen: true, resumeStepId: "last", completed: false }));
    mount();
    act(() => requestTour("welcome"));
    fireEvent.click(screen.getByRole("button", { name: "Resume where I stopped" }));
    expect(screen.getByText("Title last")).toBeInTheDocument();
  });

  it("ends (resumable) instead of fighting the user when they leave the page by hand", () => {
    mount();
    act(() => requestTour("start"));
    tick(1000); // now on /p2
    expect(screen.getByTestId("where")).toHaveTextContent("/p2");
    fireEvent.click(screen.getByRole("button", { name: "leave by hand" }));
    expect(card()).toBeNull();
    expect(screen.getByTestId("where")).toHaveTextContent("/analytics");
    expect(stored()).toMatchObject({ resumeStepId: "two" });
  });

  it("finishes with a closing dialog and records that it was completed", () => {
    mount();
    act(() => requestTour("start"));
    for (let i = 0; i < 4; i++) fireEvent.click(screen.getByRole("button", { name: i === 3 ? "Finish" : "Next" }));
    expect(card()).toBeNull();
    expect(screen.getByRole("dialog", { name: "That is the tour" })).toBeInTheDocument();
    expect(stored()).toMatchObject({ completed: true, resumeStepId: null });
    fireEvent.click(screen.getAllByRole("button", { name: "Close" }).find((b) => b.textContent === "Close")!);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("exposes a progress bar, a live caption and no spotlight when the target is not on the page", () => {
    mount();
    act(() => requestTour("start"));
    expect(screen.getByRole("progressbar", { name: "Story progress" })).toHaveAttribute("aria-valuenow");
    expect(screen.getByText("Caption one").closest("[aria-live]")).toHaveAttribute("aria-live", "polite");
    expect(screen.queryByTestId("tour-spotlight")).toBeNull();
    expect(screen.getByTestId("tour-dim")).toHaveAttribute("aria-hidden", "true");
  });

  it("highlights a target that is on the page", () => {
    const el = document.createElement("div");
    el.id = "target";
    el.getBoundingClientRect = () => ({ top: 10, left: 20, width: 100, height: 40, right: 120, bottom: 50, x: 20, y: 10, toJSON: () => ({}) });
    document.body.appendChild(el);
    mount({ steps: [step("hl", "/", { targets: ["#nope", "#target"] })] });
    act(() => requestTour("start"));
    tick(200);
    expect(screen.getByTestId("tour-spotlight")).toBeInTheDocument();
    el.remove();
  });
});

describe("registered with the app", () => {
  it("contributes start, resume and welcome commands for every role", () => {
    const cmds = feature.commands ?? [];
    expect(cmds.map((c) => c.id)).toEqual(["tour.start", "tour.resume", "tour.welcome"]);
    expect(cmds.every((c) => c.minRole === undefined)).toBe(true);
  });

  it("the start command starts the tour", () => {
    seenPrefs();
    mount();
    act(() => feature.commands!.find((c) => c.id === "tour.start")!.run());
    expect(screen.getByText("Title one")).toBeInTheDocument();
  });

  it("lives in the settings slot", () => {
    expect(feature.slots?.map((s) => s.slot)).toEqual(["settings"]);
  });
});
