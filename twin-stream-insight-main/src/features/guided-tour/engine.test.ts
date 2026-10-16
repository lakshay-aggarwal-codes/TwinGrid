import { describe, expect, it } from "vitest";
import { IDLE_TOUR, currentStep, resolveSteps, resumeIndex, totalDurationMs, tourProgress, tourReducer, type TourState, type TourStep } from "./engine";
import { STORY_STEPS } from "./steps";

const mk = (id: string, route = "/", durationMs = 1000, extra: Partial<TourStep> = {}): TourStep => ({ id, route, title: id, caption: id, durationMs, ...extra });
const STEPS = [mk("a"), mk("b", "/x"), mk("c", "/y")];
const started = (from = 0): TourState => tourReducer(IDLE_TOUR, { type: "start", steps: STEPS, fromIndex: from });

describe("tour step engine", () => {
  it("starts at the first step, playing, with no time spent", () => {
    const s = started();
    expect(s).toMatchObject({ phase: "playing", index: 0, elapsedMs: 0 });
    expect(currentStep(s)?.id).toBe("a");
  });

  it("does nothing when started with no steps", () => {
    expect(tourReducer(IDLE_TOUR, { type: "start", steps: [] })).toBe(IDLE_TOUR);
  });

  it("clamps a bad start index", () => {
    expect(started(99).index).toBe(2);
    expect(started(-4).index).toBe(0);
    expect(started(Number.NaN).index).toBe(0);
  });

  it("advances on its own once a step's time is used up, carrying no leftover", () => {
    let s = started();
    s = tourReducer(s, { type: "tick", dtMs: 600 });
    expect(s).toMatchObject({ index: 0, elapsedMs: 600 });
    s = tourReducer(s, { type: "tick", dtMs: 400 });
    expect(s).toMatchObject({ index: 1, elapsedMs: 0 });
  });

  it("finishes after the last step", () => {
    let s = started(2);
    s = tourReducer(s, { type: "tick", dtMs: 1000 });
    expect(s.phase).toBe("finished");
    expect(currentStep(s)).toBeNull();
  });

  it("does not count time while paused, and counts again after resume", () => {
    let s = tourReducer(started(), { type: "pause" });
    s = tourReducer(s, { type: "tick", dtMs: 5000 });
    expect(s).toMatchObject({ phase: "paused", index: 0, elapsedMs: 0 });
    s = tourReducer(s, { type: "resume" });
    s = tourReducer(s, { type: "tick", dtMs: 500 });
    expect(s).toMatchObject({ phase: "playing", elapsedMs: 500 });
  });

  it("ignores nonsense ticks", () => {
    const s = started();
    expect(tourReducer(s, { type: "tick", dtMs: 0 })).toBe(s);
    expect(tourReducer(s, { type: "tick", dtMs: -5 })).toBe(s);
    expect(tourReducer(s, { type: "tick", dtMs: Number.NaN })).toBe(s);
  });

  it("steps by hand while paused without resuming", () => {
    let s = tourReducer(started(), { type: "pause" });
    s = tourReducer(s, { type: "next" });
    expect(s).toMatchObject({ phase: "paused", index: 1, elapsedMs: 0 });
    s = tourReducer(s, { type: "prev" });
    s = tourReducer(s, { type: "prev" });
    expect(s.index).toBe(0);
  });

  it("toggle flips playing and paused only", () => {
    const paused = tourReducer(started(), { type: "toggle" });
    expect(paused.phase).toBe("paused");
    expect(tourReducer(paused, { type: "toggle" }).phase).toBe("playing");
    expect(tourReducer(IDLE_TOUR, { type: "toggle" })).toBe(IDLE_TOUR);
  });

  it("skip leaves the tour but remembers where it was, so it can resume", () => {
    let s = started(1);
    s = tourReducer(s, { type: "skip" });
    expect(s).toMatchObject({ phase: "idle", index: 1 });
    expect(s.steps).toHaveLength(3);
    expect(currentStep(s)).toBeNull();
    expect(tourReducer(s, { type: "next" })).toBe(s);
  });

  it("close forgets everything", () => {
    expect(tourReducer(started(1), { type: "close" })).toBe(IDLE_TOUR);
  });

  it("reports progress over the whole tour", () => {
    let s = started(1);
    s = tourReducer(s, { type: "tick", dtMs: 500 });
    const p = tourProgress(s);
    expect(p).toMatchObject({ position: 2, total: 3, remainingStepMs: 500 });
    expect(p.fraction).toBeCloseTo(1500 / 3000);
    expect(tourProgress(IDLE_TOUR)).toMatchObject({ position: 0, total: 0, fraction: 0 });
  });
});

describe("resolveSteps (role and page availability)", () => {
  const all = [mk("a", "/"), mk("op", "/x", 1000, { minRole: "operator" }), mk("gone", "/not-registered"), mk("b", "/y/")];

  it("drops operator steps for a viewer and keeps them for an operator", () => {
    const paths = ["/", "/x", "/y"];
    expect(resolveSteps(all, "viewer", paths).map((s) => s.id)).toEqual(["a", "b"]);
    expect(resolveSteps(all, "operator", paths).map((s) => s.id)).toEqual(["a", "op", "b"]);
  });

  it("drops steps whose page does not exist, so the tour never walks into a 404", () => {
    expect(resolveSteps(all, "operator", ["/", "/x"]).map((s) => s.id)).toEqual(["a", "op"]);
  });

  it("treats an unknown or missing role as the least privileged", () => {
    expect(resolveSteps(all, null, ["/", "/x", "/y"]).map((s) => s.id)).toEqual(["a", "b"]);
    expect(resolveSteps(all, "superuser", ["/", "/x", "/y"]).map((s) => s.id)).toEqual(["a", "b"]);
  });

  it("resumes at the remembered step, or the beginning when it is gone", () => {
    expect(resumeIndex(STEPS, "c")).toBe(2);
    expect(resumeIndex(STEPS, "removed-step")).toBe(0);
    expect(resumeIndex(STEPS, null)).toBe(0);
  });
});

describe("the story", () => {
  const paths = STORY_STEPS.map((s) => s.route);

  it("is about three minutes for an operator and shorter for a viewer", () => {
    const operator = resolveSteps(STORY_STEPS, "operator", paths);
    const viewer = resolveSteps(STORY_STEPS, "viewer", paths);
    expect(totalDurationMs(operator)).toBeGreaterThanOrEqual(170_000);
    expect(totalDurationMs(operator)).toBeLessThanOrEqual(190_000);
    expect(viewer.length).toBeLessThan(operator.length);
    expect(viewer.every((s) => s.minRole === undefined)).toBe(true);
  });

  it("has unique ids, absolute routes and a caption on every step", () => {
    expect(new Set(STORY_STEPS.map((s) => s.id)).size).toBe(STORY_STEPS.length);
    for (const s of STORY_STEPS) {
      expect(s.route.startsWith("/")).toBe(true);
      expect(s.title.length).toBeGreaterThan(0);
      expect(s.caption.length).toBeGreaterThan(20);
      expect(s.durationMs).toBeGreaterThanOrEqual(8000);
    }
  });

  it("never claims more than the project can show (honesty words)", () => {
    const text = STORY_STEPS.map((s) => `${s.title} ${s.caption}`).join(" ").toLowerCase();
    for (const banned of ["measured", "real facility", "validated", "production-ready", "optimal", "calibrated", "wcag"]) {
      expect(text).not.toContain(banned);
    }
    expect(text).toContain("simulat");
  });
});
