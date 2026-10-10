/// <reference lib="dom" />
import { test, expect, type CDPSession, type Page, type TestInfo, type WebSocketRoute } from "@playwright/test";
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";
import { signIn } from "./helpers";

/**
 * FE-20: performance MEASUREMENT (Section 15). This file measures; it changes nothing in the app. Optimisation is
 * FE-20b and happens only for a budget this file shows to be breached.
 *
 * Rules (same as the rest of e2e/**): real backend, seeded E2E_VIEWER_* account, NO request interception. The only
 * transport interception is the WebSocket drop used by the idle-GPU test (same as stale-surfaces.spec.ts). The probes
 * below only OBSERVE: counters/timers wrapped around WebSocket, setInterval, WebGL draw calls, long tasks, and (render
 * count test only) a read-only React DevTools hook. No data is altered, throttled or dropped by a probe.
 *
 * Gated: nothing here runs unless PERF=1 (the S1 soak alone takes PERF_SOAK_MINUTES, default 30). Run:
 *   PERF=1 PERF_RACKS=36 E2E_VIEWER_USERNAME=... E2E_VIEWER_PASSWORD=... npx playwright test e2e/perf.spec.ts
 * Optional: PERF_SOAK_MINUTES=2 (smoke only; heap/soak numbers are then NOT S1), PERF_WRITE_RESULTS=1 (writes
 * docs/frontend/perf/results/<name>.json), PERF_HEAP_SNAPSHOT=1 (heap snapshots into test-results/), PERF_DIST=dist.
 * Procedure, budgets and the breach list: docs/frontend/perf/FE-20.md.
 */

// ------------------------------------------------------------------------------------------------ budgets (Section 15)
const BUDGET = {
  parseP95Ms: 2,
  idleLongTasks: 0,
  longTasksPerCameraAnimation: 1,
  idleDrawCalls: 0,
  cameraFps: 50,
  heapGrowthRatio: 0.1,
  leakedIntervals: 0,
  initialJsGrowthRatio: 0.1,
  stateRequestsOnLoad: 1,
  whatifRequestsOnLoad: 0,
  sockets: 1,
} as const;

/** CPU throttle rate named by scenario S1 and the camera budget. */
const THROTTLE = 4;
/** Warm-up excluded from soak numbers: first paint, shader compile, first frames. */
const WARMUP_MS = 60_000;
/**
 * FE-00 reference for "Initial JS for /": sum of the three gzip JS chunks recorded in docs/frontend/baseline/BASELINE.md
 * (three 218.63 + index 196.87 + Index 170.36 kB). FE-00 did not record which chunks `/` loaded, so this takes the
 * largest reading (all three); see FE-20.md "Assumptions".
 */
const FE00_INITIAL_JS_GZIP_BYTES = Math.round((218.63 + 196.87 + 170.36) * 1000);

const RUN = process.env.PERF === "1";
const SOAK_MINUTES = Number(process.env.PERF_SOAK_MINUTES ?? "30");

test.skip(!RUN, "performance measurement is opt-in: set PERF=1 (see docs/frontend/perf/FE-20.md)");
test.describe.configure({ mode: "serial" });

// ------------------------------------------------------------------------------------------------ in-page probes
type ProbeOptions = { react: boolean };

declare global {
  interface Window {
    __perf: {
      longTasks: { start: number; duration: number }[];
      parseMs: number[];
      messageTimes: number[];
      sockets: { created: number; open: number };
      intervals: Set<number>;
      draws: number;
      commits: { t: number; rendered: string[] }[];
      reset(): void;
      sampleFrames(durationMs: number): Promise<{ t: number; drew: boolean }[]>;
    };
  }
}

function installProbes(opts: ProbeOptions) {
  const P = {
    longTasks: [] as { start: number; duration: number }[],
    parseMs: [] as number[],
    messageTimes: [] as number[],
    sockets: { created: 0, open: 0 },
    intervals: new Set<number>(),
    draws: 0,
    commits: [] as { t: number; rendered: string[] }[],
    reset() {
      P.longTasks.length = 0;
      P.parseMs.length = 0;
      P.messageTimes.length = 0;
      P.draws = 0;
      P.commits.length = 0;
    },
    sampleFrames(durationMs: number) {
      return new Promise<{ t: number; drew: boolean }[]>((resolve) => {
        const out: { t: number; drew: boolean }[] = [];
        const t0 = performance.now();
        let lastDraws = P.draws;
        const tick = (t: number) => {
          out.push({ t, drew: P.draws !== lastDraws });
          lastDraws = P.draws;
          if (t - t0 < durationMs) requestAnimationFrame(tick);
          else resolve(out);
        };
        requestAnimationFrame(tick);
      });
    },
  };
  (window as unknown as { __perf: typeof P }).__perf = P;

  try {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) P.longTasks.push({ start: e.startTime, duration: e.duration });
    }).observe({ type: "longtask", buffered: true } as unknown as PerformanceObserverInit);
  } catch {
    /* longtask unsupported: the tests assert the probe is alive */
  }

  // WebSocket: lifecycle counts + time spent in the app's message handler (parse + contract + store update, synchronous).
  const NativeWS = window.WebSocket;
  const desc = Object.getOwnPropertyDescriptor(NativeWS.prototype, "onmessage");
  if (desc?.set && desc.get) {
    const { get, set } = desc;
    Object.defineProperty(NativeWS.prototype, "onmessage", {
      configurable: true,
      get() {
        return get.call(this);
      },
      set(fn: ((this: WebSocket, ev: MessageEvent) => unknown) | null) {
        if (typeof fn !== "function") return set.call(this, fn);
        set.call(this, function (this: WebSocket, ev: MessageEvent) {
          const t = performance.now();
          try {
            return fn.call(this, ev);
          } finally {
            P.parseMs.push(performance.now() - t);
            P.messageTimes.push(t);
          }
        });
      },
    });
  }
  const OrigCtor = NativeWS;
  const Wrapped = function (this: unknown, url: string | URL, protocols?: string | string[]) {
    const ws = new OrigCtor(url, protocols);
    P.sockets.created++;
    (ws as unknown as { __counted?: boolean }).__counted = true;
    ws.addEventListener("open", () => P.sockets.open++);
    ws.addEventListener("close", () => P.sockets.open--);
    return ws;
  } as unknown as typeof WebSocket;
  Wrapped.prototype = OrigCtor.prototype;
  Object.assign(Wrapped, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 });
  window.WebSocket = Wrapped;

  // Live intervals (a leaked subscription/timer shows up as growth that survives navigation).
  const si = window.setInterval.bind(window);
  const ci = window.clearInterval.bind(window);
  window.setInterval = ((h: TimerHandler, t?: number, ...a: unknown[]) => {
    const id = si(h, t, ...a);
    P.intervals.add(id as unknown as number);
    return id;
  }) as typeof window.setInterval;
  window.clearInterval = ((id?: number) => {
    if (id !== undefined) P.intervals.delete(id);
    ci(id);
  }) as typeof window.clearInterval;

  // WebGL: count draw calls (frames are the draw bursts; the canvas uses frameloop="demand").
  for (const proto of [window.WebGLRenderingContext?.prototype, window.WebGL2RenderingContext?.prototype]) {
    if (!proto) continue;
    for (const name of ["drawArrays", "drawElements", "drawArraysInstanced", "drawElementsInstanced", "drawRangeElements"] as const) {
      const orig = (proto as unknown as Record<string, (...a: unknown[]) => unknown>)[name];
      if (typeof orig !== "function") continue;
      (proto as unknown as Record<string, unknown>)[name] = function (this: unknown, ...a: unknown[]) {
        P.draws++;
        return orig.apply(this, a);
      };
    }
  }

  // Render counts (dev build only; read-only DevTools hook). Off for every test except the render-count test because
  // walking the fibre tree on each commit costs time and would distort the other numbers.
  if (opts.react) {
    const PERFORMED_WORK = 1;
    const nameOf = (f: { type?: { displayName?: string; name?: string; render?: { name?: string } } | null }) =>
      f.type?.displayName || f.type?.name || f.type?.render?.name || "anonymous";
    (window as unknown as Record<string, unknown>).__REACT_DEVTOOLS_GLOBAL_HOOK__ = {
      supportsFiber: true,
      renderers: new Map(),
      inject: () => 1,
      checkDCE() {},
      onScheduleFiberRoot() {},
      onCommitFiberUnmount() {},
      onPostCommitFiberRoot() {},
      onCommitFiberRoot(_id: number, root: { current: unknown }) {
        type Fiber = { tag: number; flags: number; type: never; child: Fiber | null; sibling: Fiber | null; alternate: Fiber | null };
        const rendered: string[] = [];
        const stack: Fiber[] = [(root.current as Fiber).child as Fiber].filter(Boolean);
        while (stack.length) {
          const f = stack.pop() as Fiber;
          // 0 function, 1 class, 11 forwardRef, 14/15 memo: components only (host nodes are not "components").
          if ([0, 1, 11, 14, 15].includes(f.tag) && f.alternate && (f.flags & PERFORMED_WORK) !== 0) rendered.push(nameOf(f));
          if (f.sibling) stack.push(f.sibling);
          if (f.child) stack.push(f.child);
        }
        P.commits.push({ t: performance.now(), rendered });
      },
    };
  }
}

// ------------------------------------------------------------------------------------------------ helpers
async function open(page: Page, opts: Partial<ProbeOptions> = {}, path = "/") {
  await page.addInitScript(installProbes, { react: false, ...opts });
  await signIn(page, "viewer", path);
}

async function cpu(page: Page, rate: number): Promise<CDPSession> {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate });
  return cdp;
}

async function jsHeapBytes(cdp: CDPSession): Promise<number> {
  await cdp.send("HeapProfiler.enable");
  await cdp.send("HeapProfiler.collectGarbage");
  await cdp.send("HeapProfiler.collectGarbage");
  const { metrics } = (await cdp.send("Performance.getMetrics")) as { metrics: { name: string; value: number }[] };
  return metrics.find((m) => m.name === "JSHeapUsedSize")?.value ?? Number.NaN;
}

async function heapSnapshot(cdp: CDPSession, testInfo: TestInfo, label: string) {
  if (process.env.PERF_HEAP_SNAPSHOT !== "1") return;
  const chunks: string[] = [];
  const onChunk = (e: { chunk: string }) => chunks.push(e.chunk);
  cdp.on("HeapProfiler.addHeapSnapshotChunk", onChunk);
  await cdp.send("HeapProfiler.takeHeapSnapshot", { reportProgress: false });
  cdp.off("HeapProfiler.addHeapSnapshotChunk", onChunk);
  const file = testInfo.outputPath(`${label}.heapsnapshot`);
  writeFileSync(file, chunks.join(""));
  await testInfo.attach(`${label}.heapsnapshot`, { path: file });
}

const percentile = (xs: number[], p: number) => {
  if (!xs.length) return Number.NaN;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.ceil((p / 100) * s.length) - 1)];
};
const median = (xs: number[]) => percentile(xs, 50);

async function probe<T>(page: Page, fn: (p: Window["__perf"]) => T): Promise<T> {
  return page.evaluate(`(${fn.toString()})(window.__perf)`) as Promise<T>;
}

/** Attach the numbers to the report (the "numbers table" evidence) and, with PERF_WRITE_RESULTS=1, keep them in docs/. */
async function record(testInfo: TestInfo, name: string, data: Record<string, unknown>) {
  const body = JSON.stringify(
    { scenario: name, at: new Date().toISOString(), throttle: data.throttle ?? null, racksAttested: process.env.PERF_RACKS ?? "unattested", ...data },
    null,
    2
  );
  await testInfo.attach(`perf-${name}.json`, { body, contentType: "application/json" });
  if (process.env.PERF_WRITE_RESULTS === "1") {
    const dir = join(process.cwd(), "docs", "frontend", "perf", "results");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, `${name}.json`), body + "\n");
  }
}

async function longTasksSince(page: Page, sinceMs: number) {
  const all = await probe(page, (p) => p.longTasks.map((t) => ({ start: t.start, duration: t.duration })));
  return all.filter((t) => t.start >= sinceMs);
}
const now = (page: Page) => page.evaluate(() => performance.now());

async function expectProbeAlive(page: Page) {
  const alive = await page.evaluate(() => typeof window.__perf === "object" && "PerformanceObserver" in window && (PerformanceObserver as unknown as { supportedEntryTypes: string[] }).supportedEntryTypes.includes("longtask"));
  expect(alive, "probes did not install / longtask is unsupported: the numbers would be meaningless").toBe(true);
}

// ------------------------------------------------------------------------------------------------ tests
test("network on Live Twin load: no /api/whatif, at most one /api/state, one WebSocket", async ({ page }, testInfo) => {
  const seen: string[] = [];
  page.on("request", (r) => seen.push(new URL(r.url()).pathname));
  await open(page);
  await expect(page.getByTestId("liveness")).toHaveAttribute("data-liveness", "live", { timeout: 45_000 });
  await page.waitForTimeout(10_000);
  const whatif = seen.filter((p) => p === "/api/whatif").length;
  const state = seen.filter((p) => p === "/api/state").length;
  const sockets = await probe(page, (p) => ({ created: p.sockets.created, open: p.sockets.open }));
  await record(testInfo, "network-on-load", { whatif, state, sockets, requests: seen.filter((p) => p.startsWith("/api/") || p.startsWith("/ws")) });
  expect(whatif).toBe(BUDGET.whatifRequestsOnLoad);
  expect(state).toBeLessThanOrEqual(BUDGET.stateRequestsOnLoad);
  expect(sockets.open).toBe(BUDGET.sockets);
});

test("S1: Live Twin soak (CPU 4x): parse P95, long tasks, heap growth", async ({ page }, testInfo) => {
  test.setTimeout((SOAK_MINUTES + 6) * 60_000);
  await open(page);
  await expectProbeAlive(page);
  const cdp = await cpu(page, THROTTLE);
  await expect(page.getByTestId("liveness")).toHaveAttribute("data-liveness", "live", { timeout: 60_000 });

  await page.waitForTimeout(WARMUP_MS);
  const heapStart = await jsHeapBytes(cdp);
  await heapSnapshot(cdp, testInfo, "s1-start");
  await probe(page, (p) => p.reset());
  const t0 = await now(page);

  const samples: { minute: number; heapUsed: number; longTasks: number; messages: number }[] = [];
  for (let m = 1; m <= SOAK_MINUTES; m++) {
    await page.waitForTimeout(60_000);
    const [lt, msgs] = await Promise.all([longTasksSince(page, t0), probe(page, (p) => p.messageTimes.length)]);
    const { metrics } = (await cdp.send("Performance.getMetrics")) as { metrics: { name: string; value: number }[] };
    samples.push({ minute: m, heapUsed: metrics.find((x) => x.name === "JSHeapUsedSize")?.value ?? Number.NaN, longTasks: lt.length, messages: msgs });
  }

  const [parse, times, longTasks] = await Promise.all([probe(page, (p) => [...p.parseMs]), probe(page, (p) => [...p.messageTimes]), longTasksSince(page, t0)]);
  const heapEnd = await jsHeapBytes(cdp);
  await heapSnapshot(cdp, testInfo, "s1-end");
  const gaps = times.slice(1).map((t, i) => (t - times[i]) / 1000);
  const parseP95 = percentile(parse, 95);
  const heapGrowth = (heapEnd - heapStart) / heapStart;
  const liveness = await page.getByTestId("liveness").getAttribute("data-liveness");

  await record(testInfo, "s1-soak", {
    throttle: THROTTLE,
    soakMinutes: SOAK_MINUTES,
    isFullS1: SOAK_MINUTES >= 30,
    warmupMs: WARMUP_MS,
    messages: parse.length,
    medianMessageGapS: median(gaps),
    parseMs: { p50: median(parse), p95: parseP95, max: Math.max(...parse) },
    longTasks: longTasks.length,
    longTaskDurationsMs: longTasks.map((t) => Math.round(t.duration)),
    heapBytes: { start: heapStart, end: heapEnd, growthRatio: heapGrowth },
    perMinute: samples,
    livenessAtEnd: liveness,
  });

  // Scenario validity first: numbers from a different scenario must not be mistaken for S1.
  expect(process.env.PERF_RACKS, "attest the rack count of the backend under test: PERF_RACKS=36").toBe("36");
  expect(median(gaps), "feed interval is not ~3 s: this is not scenario S1").toBeGreaterThan(2.5);
  expect(median(gaps), "feed interval is not ~3 s: this is not scenario S1").toBeLessThan(3.5);
  expect(SOAK_MINUTES, "PERF_SOAK_MINUTES < 30: smoke run, not S1").toBeGreaterThanOrEqual(30);
  expect(liveness, "feed was not live at the end of the soak: numbers describe a degraded run").toBe("live");

  expect(parseP95).toBeLessThanOrEqual(BUDGET.parseP95Ms);
  expect(longTasks.length).toBeLessThanOrEqual(BUDGET.idleLongTasks);
  expect(heapGrowth).toBeLessThanOrEqual(BUDGET.heapGrowthRatio);
});

test("idle GPU: no frames are rendered while nothing changes", async ({ page }, testInfo) => {
  // Same transport-only interception as stale-surfaces.spec.ts: the socket is closed so NO new frame can invalidate
  // the scene, then the page is left alone. Frames are forwarded unmodified until the drop.
  let dropped = false;
  const conn: { current: { page: WebSocketRoute; server: WebSocketRoute } | null } = { current: null };
  await page.routeWebSocket(/\/ws\/live/, (ws) => {
    if (dropped) {
      void ws.close({ code: 1012, reason: "e2e: socket dropped" });
      return;
    }
    conn.current = { page: ws, server: ws.connectToServer() };
  });
  await open(page);
  await expectProbeAlive(page);
  await expect(page.getByTestId("liveness")).toHaveAttribute("data-liveness", "live", { timeout: 45_000 });
  dropped = true;
  await conn.current?.server.close();
  await conn.current?.page.close({ code: 1012, reason: "e2e: socket dropped" });
  await expect(page.getByTestId("liveness")).not.toHaveAttribute("data-liveness", "live", { timeout: 60_000 });
  await page.waitForTimeout(10_000); // let state-change redraws settle
  await probe(page, (p) => p.reset());
  const frames = await page.evaluate(() => window.__perf.sampleFrames(10_000));
  const draws = await probe(page, (p) => p.draws);
  await record(testInfo, "idle-gpu", { windowMs: 10_000, rafTicks: frames.length, drawCalls: draws, framesWithDraws: frames.filter((f) => f.drew).length });
  expect(frames.length, "rAF sampler did not run").toBeGreaterThan(10);
  expect(draws).toBeLessThanOrEqual(BUDGET.idleDrawCalls);
});

test("camera focus animation (CPU 4x): >= 50 fps, at most 1 long task per animation", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  await open(page);
  await expectProbeAlive(page);
  await cpu(page, THROTTLE);
  await expect(page.getByTestId("liveness")).toHaveAttribute("data-liveness", "live", { timeout: 60_000 });
  const scene = page.getByRole("group", { name: /3D facility view/ });
  await scene.focus();

  const runs: { fps: number; renderedFrames: number; durationMs: number; longTasks: number }[] = [];
  for (let i = 0; i < 5; i++) {
    await page.keyboard.press("ArrowRight"); // select a rack (selection tween settles first)
    await page.waitForTimeout(1500);
    await probe(page, (p) => p.reset());
    const t0 = await now(page);
    const sampling = page.evaluate(() => window.__perf.sampleFrames(2200)); // camera tween is 1.1 s
    await page.keyboard.press("Enter"); // zoom to the selected rack (camera focus tween)
    const frames = await sampling;
    // The animation = from the first draw to the last draw before a >=200 ms stretch without any.
    const drawn = frames.filter((f) => f.drew);
    expect(drawn.length, "no frame was drawn for the camera focus: cannot measure").toBeGreaterThan(2);
    let end = drawn[0].t;
    for (const f of drawn) {
      if (f.t - end > 200) break;
      end = f.t;
    }
    const inAnim = drawn.filter((f) => f.t <= end);
    const durationMs = end - inAnim[0].t;
    const lt = await longTasksSince(page, t0);
    runs.push({ fps: durationMs > 0 ? ((inAnim.length - 1) / durationMs) * 1000 : 0, renderedFrames: inAnim.length, durationMs, longTasks: lt.length });
    await page.keyboard.press("Escape");
    await page.waitForTimeout(500);
  }
  await record(testInfo, "camera-focus", { throttle: THROTTLE, runs, medianFps: median(runs.map((r) => r.fps)), worstFps: Math.min(...runs.map((r) => r.fps)) });
  expect(median(runs.map((r) => r.fps))).toBeGreaterThanOrEqual(BUDGET.cameraFps);
  for (const r of runs) expect(r.longTasks).toBeLessThanOrEqual(BUDGET.longTasksPerCameraAnimation);
});

test("render count per feed tick is recorded for the subscriber-list comparison (dev build)", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  await open(page, { react: true });
  await expect(page.getByTestId("liveness")).toHaveAttribute("data-liveness", "live", { timeout: 45_000 });
  await page.waitForTimeout(3000);
  await probe(page, (p) => p.reset());
  await page.waitForTimeout(30_000); // ~10 ticks at 3 s
  const { commits, ticks } = await probe(page, (p) => ({ commits: p.commits.map((c) => ({ t: c.t, rendered: c.rendered })), ticks: p.messageTimes.slice() }));
  expect(commits.length, "no commits observed: this is a production build or the React hook was not picked up (run against `npm run dev`)").toBeGreaterThan(0);
  // Attribute each commit to the tick that precedes it (commits within 250 ms after a message).
  const perTick = ticks.map((t) => {
    const cs = commits.filter((c) => c.t >= t && c.t < t + 250);
    const counts: Record<string, number> = {};
    for (const c of cs) for (const n of c.rendered) counts[n] = (counts[n] ?? 0) + 1;
    return { commits: cs.length, componentsRendered: cs.reduce((a, c) => a + c.rendered.length, 0), byComponent: counts };
  });
  await record(testInfo, "render-count", {
    note: "Compare byComponent with the list of components subscribed to a CHANGED field (FE-20.md). Not asserted: the budget is relative to that list.",
    ticks: perTick.length,
    medianComponentsPerTick: median(perTick.map((p) => p.componentsRendered)),
    perTick,
  });
});

test("S2: open/close each panel 50x: no leaked timers or sockets, heap and long tasks recorded", async ({ page }, testInfo) => {
  test.setTimeout(300_000);
  await open(page);
  await expectProbeAlive(page);
  const cdp = await cpu(page, THROTTLE);
  await expect(page.getByTestId("liveness")).toHaveAttribute("data-liveness", "live", { timeout: 60_000 });
  const results: Record<string, unknown> = {};
  for (const name of ["Simulation Lab", "Operations", "Incidents"]) {
    const toggle = page.getByRole("button", { name, exact: true });
    // One warm cycle so one-off lazy chunks/caches are not counted as growth.
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    const heap0 = await jsHeapBytes(cdp);
    const intervals0 = await probe(page, (p) => p.intervals.size);
    const sockets0 = await probe(page, (p) => p.sockets.open);
    await probe(page, (p) => p.reset());
    const t0 = await now(page);
    for (let i = 0; i < 50; i++) {
      await toggle.click();
      await expect(toggle).toHaveAttribute("aria-pressed", "true");
      await toggle.click();
      await expect(toggle).toHaveAttribute("aria-pressed", "false");
    }
    await page.waitForTimeout(1000);
    const heap1 = await jsHeapBytes(cdp);
    const intervals1 = await probe(page, (p) => p.intervals.size);
    const sockets1 = await probe(page, (p) => p.sockets.open);
    const lt = await longTasksSince(page, t0);
    results[name] = {
      cycles: 50,
      heapBytes: { before: heap0, after: heap1, growthRatio: (heap1 - heap0) / heap0 },
      intervals: { before: intervals0, after: intervals1 },
      openSockets: { before: sockets0, after: sockets1 },
      longTasks: lt.length,
      longTaskDurationsMs: lt.map((t) => Math.round(t.duration)),
    };
    expect(intervals1 - intervals0, `${name}: timers grew across 50 open/close cycles`).toBeLessThanOrEqual(BUDGET.leakedIntervals);
    expect(sockets1, `${name}: sockets changed`).toBe(sockets0);
  }
  await record(testInfo, "s2-panels", { throttle: THROTTLE, panels: results });
});

test("subscriptions after unmount: navigating away from and back to Live Twin does not accumulate timers or sockets", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  await open(page);
  await expect(page.getByTestId("liveness")).toHaveAttribute("data-liveness", "live", { timeout: 45_000 });
  const spa = async (path: string) => {
    await page.evaluate((p) => {
      history.pushState({}, "", p);
      window.dispatchEvent(new PopStateEvent("popstate"));
    }, path);
    await page.waitForTimeout(1500);
  };
  const snap = () => probe(page, (p) => ({ intervals: p.intervals.size, openSockets: p.sockets.open, created: p.sockets.created }));
  const cycles: { intervals: number; openSockets: number; created: number }[] = [];
  for (let i = 0; i < 6; i++) {
    await spa("/analytics");
    await spa("/");
    cycles.push(await snap());
  }
  await record(testInfo, "unmount-leaks", {
    cycles,
    note: "Page-level proxy: a component-level 'subscriptions after unmount = 0' test needs a src/** test (outside this task's allowance).",
  });
  const [first, last] = [cycles[0], cycles[cycles.length - 1]];
  expect(last.intervals - first.intervals).toBeLessThanOrEqual(BUDGET.leakedIntervals);
  expect(last.openSockets).toBeLessThanOrEqual(BUDGET.sockets);
});

test("S3: /analytics 24-point simulation: time to results and long tasks", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  await open(page, {}, "/analytics");
  await expectProbeAlive(page);
  await cpu(page, THROTTLE);
  await page.getByRole("tab", { name: /24h Simulation/ }).click();
  await probe(page, (p) => p.reset());
  const t0 = await now(page);
  await page.getByRole("button", { name: /Run 24h Simulation/ }).click();
  const frames = page.getByTestId("chart-frame");
  await expect(frames).toHaveCount(3, { timeout: 120_000 });
  const tDone = await now(page);
  await page.waitForTimeout(2000);
  const lt = await longTasksSince(page, t0);
  const simMs = tDone - t0;

  await page.getByRole("tab", { name: /What-If Scenarios/ }).click();
  await page.waitForTimeout(3000);
  const ltAfterWhatIfTab = (await longTasksSince(page, t0)).length;

  await record(testInfo, "s3-analytics", {
    throttle: THROTTLE,
    clickToThreeChartsMs: simMs,
    longTasks: lt.length,
    longTaskDurationsMs: lt.map((t) => Math.round(t.duration)),
    longTasksIncludingWhatIfTabOpen: ltAfterWhatIfTab,
    note: "Click-to-charts includes the real backend run time (not frontend cost). Long tasks are the frontend-attributable figure.",
  });
  // No budget row covers S3 directly; it is recorded so a breach finding can cite numbers. Probe liveness only.
  expect(simMs).toBeGreaterThan(0);
});

test("S4: 5,000-point history window: render cost (needs a backend holding >= 5,000 stored samples)", async ({ page }, testInfo) => {
  test.setTimeout(240_000);
  let points = 0;
  page.on("response", async (r) => {
    if (/\/api\/telemetry\/sensors\/[^/]+\/samples/.test(new URL(r.url()).pathname) && r.ok()) {
      try {
        const body = (await r.json()) as { items?: unknown[] };
        points += body.items?.length ?? 0; // observed, never altered
      } catch {
        /* non-JSON: ignore */
      }
    }
  });
  await open(page, {}, "/telemetry");
  await expectProbeAlive(page);
  await cpu(page, THROTTLE);
  await probe(page, (p) => p.reset());
  const t0 = await now(page);
  await page.getByLabel("Window").selectOption({ label: "Last 168 hours (backend maximum)" });
  await expect(page.getByTestId("history-view")).toBeVisible({ timeout: 120_000 });
  await page.waitForTimeout(3000);
  const tDone = await now(page);
  const lt = await longTasksSince(page, t0);
  await record(testInfo, "s4-history", {
    throttle: THROTTLE,
    pointsLoaded: points,
    reachedS4: points >= 5000,
    windowChangeToChartMs: tDone - t0,
    longTasks: lt.length,
    longTaskDurationsMs: lt.map((t) => Math.round(t.duration)),
  });
  test.skip(points < 5000, `S4 not reachable: the backend returned ${points} stored points for the widest window (< 5,000). Recorded as UNMEASURED, not as a pass.`);
  expect(points).toBeGreaterThanOrEqual(5000);
});

test("initial JS for / is within FE-00 + 10% (production build output)", async ({ baseURL }, testInfo) => {
  const dist = join(process.cwd(), process.env.PERF_DIST ?? "dist");
  test.skip(!existsSync(join(dist, "index.html")), `no ${dist}/index.html: build first (see FE-20.md; the dev server is not representative for bundle size)`);
  const html = readFileSync(join(dist, "index.html"), "utf8");
  const initial = new Set<string>();
  for (const m of html.matchAll(/<(?:script|link)[^>]+(?:src|href)="(\/?assets\/[^"]+\.js)"[^>]*>/g)) initial.add(m[1].replace(/^\//, ""));
  expect(initial.size, "no initial scripts found in dist/index.html").toBeGreaterThan(0);
  const sizes = [...initial].map((f) => ({ file: f, gzip: gzipSync(readFileSync(join(dist, f))).length }));
  const total = sizes.reduce((a, s) => a + s.gzip, 0);
  const all = readdirSync(join(dist, "assets")).filter((f) => f.endsWith(".js"));
  await record(testInfo, "initial-js", {
    baseURL,
    initialChunks: sizes,
    initialGzipBytes: total,
    fe00ReferenceGzipBytes: FE00_INITIAL_JS_GZIP_BYTES,
    ratio: total / FE00_INITIAL_JS_GZIP_BYTES,
    allJsChunks: all.length,
    note: "Initial = scripts and modulepreloads referenced by dist/index.html. Lazy chunks are not initial.",
  });
  expect(total).toBeLessThanOrEqual(FE00_INITIAL_JS_GZIP_BYTES * (1 + BUDGET.initialJsGrowthRatio));
});
