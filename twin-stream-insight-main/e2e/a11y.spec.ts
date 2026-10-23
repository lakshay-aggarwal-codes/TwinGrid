import { test, expect, type Page, type TestInfo } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { signIn } from "./helpers";

/**
 * FE-03 accessibility harness. Runs axe on routes that need NO backend data (the sign-in screen).
 * Later tasks add their own routes/open panels here (FE-19 widens the coverage) instead of deferring a11y to the end.
 * FE-19: the signed-in sections below cover every route and every open panel (0 serious/critical) and the Section 13
 * keyboard flows. They need the real backend + seeded E2E_VIEWER_* account (see helpers.ts); the login tests above do not.
 *
 * IG-06: the sweep also covers /evaluation, /telemetry and /runs/:id. /runs/:id scans a REAL run when E2E_RUN_ID names one
 * that exists on the backend under test (optional; the account in E2E_VIEWER_* must be allowed to read it); without it the
 * test scans the page's unknown-run state and labels the axe attachment accordingly. Nothing is intercepted.
 *
 * Runs against the REAL backend (FE-11 rule: nothing in e2e/** intercepts a request). A fresh browser context has no
 * session, so the app's own refresh attempt is rejected by the backend and it lands on the login screen.
 */
const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function openLogin(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Sign in to TwinGrid/ })).toBeVisible();
}

for (const colorScheme of ["light", "dark"] as const) {
  test(`login screen has no axe violations (${colorScheme} scheme)`, async ({ page }) => {
    await page.emulateMedia({ colorScheme });
    await openLogin(page);
    const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
    expect(results.violations, JSON.stringify(results.violations.map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) })), null, 2)).toEqual([]);
  });
}

test("login screen: credentials the backend rejects produce an alert associated with the sign-in form and no axe violations", async ({ page }) => {
  await openLogin(page);
  // Credentials that do not exist on the backend under test: the real backend rejects them.
  await page.getByLabel("Username").fill("a11y-no-such-user");
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  expect(results.violations).toEqual([]);
});

// ------------------------------------------------------------------------------------------------------------------
// FE-19: signed-in sweep (real backend; nothing is intercepted). Gate = zero serious/critical violations. The full axe
// result of every scan is attached to the test report (the "axe reports" evidence artifact), minor/moderate included.
// ------------------------------------------------------------------------------------------------------------------

async function scan(page: Page, testInfo: TestInfo, label: string) {
  // Route changes fade in (RotateTransition). Axe must not sample mid-fade (it reads blended colours, e.g. 3.74:1 for a
  // token that is 4.5:1+ at full opacity), so wait until the page <h1> and all its ancestors are fully opaque.
  // Pages without an <h1> (dialogs, drawers) have nothing to wait for.
  await page.waitForFunction(
    () => {
      const h = document.querySelector("h1");
      if (!h) return true;
      let opacity = 1;
      for (let e: Element | null = h; e; e = e.parentElement) opacity *= parseFloat(getComputedStyle(e).opacity || "1");
      return opacity >= 0.999;
    },
    undefined,
    { timeout: 10_000 }
  );
  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  await testInfo.attach(`axe-${label}.json`, { body: JSON.stringify(results.violations, null, 2), contentType: "application/json" });
  const blocking = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(
    blocking,
    JSON.stringify(blocking.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.map((n) => n.target) })), null, 2)
  ).toEqual([]);
}

/**
 * IG-06: `signIn(page, role, path)` from helpers.ts waits for the "Live Twin" <h1> after submitting the form, and only the
 * `/` page renders that heading, so signing in at any other path times out (20 s) before a single axe scan. The session lives
 * in memory (a full page.goto drops it), so: sign in at `/`, then move to the route client-side, as evaluation.spec.ts does.
 */
async function signInAndGo(page: Page, path: string) {
  await signIn(page, "viewer", "/");
  if (path === "/") return;
  await page.evaluate((to) => {
    window.history.pushState({}, "", to);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, path);
  await expect(page).toHaveURL((url) => url.pathname === path);
}

const ROUTES: ReadonlyArray<{ path: string; heading: RegExp }> = [
  { path: "/", heading: /^Live Twin$/ },
  { path: "/analytics", heading: /Analytics/ },
  { path: "/runs", heading: /./ },
  // IG-06: the routes added by FE-17 / FE-18 / FE-16 detail. The page <h1> renders before the data does, so each scan
  // waits for the network to settle first (bounded; a never-idle page fails here rather than being scanned half-loaded).
  { path: "/evaluation", heading: /^Policy evaluation$/ },
  { path: "/telemetry", heading: /^Telemetry history$/ },
];

for (const colorScheme of ["light", "dark"] as const) {
  for (const route of ROUTES) {
    test(`route ${route.path} has no serious/critical axe violations (${colorScheme})`, async ({ page }, testInfo) => {
      await page.emulateMedia({ colorScheme });
      await signInAndGo(page, route.path);
      await expect(page.getByRole("heading", { name: route.heading }).first()).toBeVisible();
      await page.waitForLoadState("networkidle", { timeout: 30_000 });
      await scan(page, testInfo, `route${route.path.replace(/\//g, "-") || "-root"}-${colorScheme}`);
    });
  }
}

// IG-06: /runs/:id. A real run when E2E_RUN_ID is set; otherwise the unknown-run state (labelled in the attachment name,
// so a clean result here is never read as "a live run was scanned").
for (const colorScheme of ["light", "dark"] as const) {
  const runId = process.env.E2E_RUN_ID?.trim();
  test(`route /runs/:id (${runId ? "real run" : "unknown-run state"}) has no serious/critical axe violations (${colorScheme})`, async ({ page }, testInfo) => {
    await page.emulateMedia({ colorScheme });
    await signInAndGo(page, `/runs/${encodeURIComponent(runId || "a11y-no-such-run")}`);
    await expect(page.getByRole("heading", { level: 1, name: /^Run$/ })).toBeVisible();
    await page.waitForLoadState("networkidle", { timeout: 30_000 });
    await scan(page, testInfo, `route-runs-id-${runId ? "real-run" : "unknown-run-state"}-${colorScheme}`);
  });
}

test("analytics: every chart has a title, a text summary and a data table", async ({ page }, testInfo) => {
  await signInAndGo(page, "/analytics");
  await page.getByRole("tab", { name: /24h Simulation/ }).click();
  await page.getByRole("button", { name: /Run 24h Simulation/ }).click();
  const frames = page.getByTestId("chart-frame");
  await expect(frames).toHaveCount(3, { timeout: 30_000 });
  for (let i = 0; i < 3; i++) {
    const frame = frames.nth(i);
    await expect(frame.getByTestId("chart-summary")).toContainText("Simulated run result, not live");
    await frame.getByRole("button", { name: "View data table" }).click();
    await expect(frame.getByRole("table")).toBeVisible();
  }
  await scan(page, testInfo, "analytics-simulation-tables-open");
});

const PANELS = [
  { toggle: "Simulation Lab", close: "Close simulation lab" },
  { toggle: "Operations", close: "Close operations console" },
  { toggle: "Incidents", close: "Close incidents" },
] as const;

for (const panel of PANELS) {
  test(`panel "${panel.toggle}": axe clean; opening focuses its heading; closing returns focus to the toggle (keyboard only)`, async ({ page }, testInfo) => {
    await signIn(page, "viewer");
    const toggle = page.getByRole("button", { name: panel.toggle, exact: true });
    await toggle.focus();
    await page.keyboard.press("Enter");
    const region = page.getByRole("complementary", { name: new RegExp(panel.toggle, "i") });
    await expect(region).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: new RegExp(panel.toggle, "i") })).toBeFocused();
    await scan(page, testInfo, `panel-${panel.toggle.toLowerCase().replace(/ /g, "-")}`);

    await page.getByRole("button", { name: panel.close }).focus();
    await page.keyboard.press("Enter");
    await expect(region).toBeHidden();
    await expect(toggle).toBeFocused();
  });
}

test("inspector: clearing the selection by keyboard keeps focus on the inspector heading", async ({ page }, testInfo) => {
  await signIn(page, "viewer");
  await page.getByRole("group", { name: /3D facility view/ }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("button", { name: "Clear selection" })).toBeVisible();
  await scan(page, testInfo, "inspector-rack-selected");
  await page.getByRole("button", { name: "Clear selection" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 2, name: "Inspector" })).toBeFocused();
});

test("command palette: axe clean, focus is trapped, Escape returns focus to the invoking control", async ({ page }, testInfo) => {
  await signIn(page, "viewer");
  const invoker = page.getByRole("button", { name: "Search racks, zones and alerts" });
  await invoker.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await scan(page, testInfo, "command-palette");
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(invoker).toBeFocused();
});

test("command palette via Ctrl+K from the 3D view returns focus to the 3D view", async ({ page }) => {
  await signIn(page, "viewer");
  const scene = page.getByRole("group", { name: /3D facility view/ });
  await scene.focus();
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(scene).toBeFocused();
});

test("reduced motion: no infinite animation is running on the Live Twin or Analytics", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signIn(page, "viewer");
  const running = () =>
    page.evaluate(() =>
      document
        .getAnimations()
        .filter((a) => a.playState === "running" && a.effect?.getTiming().iterations === Infinity)
        .map((a) => (a.effect as KeyframeEffect | null)?.target?.className ?? "")
    );
  expect(await running()).toEqual([]);
  await page.getByRole("link", { name: "Analytics" }).click();
  await expect(page).toHaveURL(/\/analytics$/);
  expect(await running()).toEqual([]);
});

// ------------------------------------------------------------------------------------------------------------------
// Task 28 (QA-003): the sweep widened to the routes and surfaces added since FE-19 (alerts centre, what-if lab, optimizer
// approvals, report, fleet, admin incl. the access-request queue, the request / pending / activation pages, the model
// passport and assistant drawers). Same rules: real backend, nothing intercepted, gate = zero serious/critical axe findings,
// every full result attached. Extra environment for this block: E2E_ADMIN_USERNAME / E2E_ADMIN_PASSWORD (an admin account).
// There is no /evidence route in this tree (Task 26 is not merged): that row of the sweep is recorded as absent, not scanned.
// Reflow checks are automated approximations (320 px width; 640 x 512 stands in for 200 % zoom of 1280 x 1024). They do not
// replace the manual pass listed in docs/frontend/a11y/FE-19.md.
// ------------------------------------------------------------------------------------------------------------------

function adminCredentials(): { username: string; password: string } {
  const username = process.env.E2E_ADMIN_USERNAME;
  const password = process.env.E2E_ADMIN_PASSWORD;
  if (!username || !password) throw new Error("Set E2E_ADMIN_USERNAME and E2E_ADMIN_PASSWORD (an existing admin account on the backend under test).");
  return { username, password };
}

async function signInAsAdmin(page: Page): Promise<void> {
  adminCredentials(); // fails early with the admin-specific message when E2E_ADMIN_* is not set
  // The shared helper waits out the backend's 10/minute sign-in limiter; a single click here read a 429 as a broken page.
  await signIn(page, "admin");
}

/** Move to a route client-side (the session is in memory; a full page.goto would drop it). */
async function goClient(page: Page, path: string): Promise<void> {
  await page.evaluate((to) => {
    window.history.pushState({}, "", to);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, path);
  await expect(page).toHaveURL((url) => url.pathname === path);
}

/** Keyboard focus must be visible: an outline or a ring (box-shadow) on the focused element. */
async function expectVisibleFocus(page: Page, label: string): Promise<void> {
  const style = await page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return null;
    const cs = getComputedStyle(el);
    return { outline: cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0, ring: cs.boxShadow !== "none" };
  });
  expect(style, `${label}: nothing has focus`).not.toBeNull();
  expect(style && (style.outline || style.ring), `${label}: focused element has no visible focus indicator`).toBe(true);
}

async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}

const VIEWER_ROUTES: ReadonlyArray<{ path: string; heading: RegExp }> = [
  { path: "/alerts", heading: /^Alerts centre$/ },
  { path: "/whatif-lab", heading: /^What-if lab$/ },
  { path: "/optimizer", heading: /^Optimizer$/ },
  { path: "/report", heading: /./ },
  { path: "/fleet", heading: /^Fleet view$/ },
];

for (const colorScheme of ["light", "dark"] as const) {
  for (const route of VIEWER_ROUTES) {
    test(`T28 route ${route.path} has no serious/critical axe violations (${colorScheme})`, async ({ page }, testInfo) => {
      await page.emulateMedia({ colorScheme });
      await signInAndGo(page, route.path);
      await expect(page.getByRole("heading", { name: route.heading }).first()).toBeVisible({ timeout: 20_000 });
      await page.waitForLoadState("networkidle", { timeout: 30_000 });
      await scan(page, testInfo, `t28${route.path.replace(/\//g, "-")}-${colorScheme}`);
    });
  }
}

test("T28 model passport drawer: axe clean, focus moves in, Escape returns focus to the opener", async ({ page }, testInfo) => {
  await signIn(page, "viewer");
  const opener = page.getByTestId("model-passport-button").first();
  await opener.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: /Model passport/i });
  await expect(dialog).toBeVisible({ timeout: 20_000 });
  expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  await page.waitForLoadState("networkidle", { timeout: 30_000 });
  await scan(page, testInfo, "t28-passport-drawer");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(opener).toBeFocused();
});

test("T28 assistant drawer: axe clean, focus trapped, live region present, Escape returns focus to Ask", async ({ page }, testInfo) => {
  await signIn(page, "viewer");
  const ask = page.getByTestId("assistant-open");
  await ask.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByTestId("assistant-drawer");
  await expect(dialog).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("assistant-live")).toHaveAttribute("aria-live", "polite");
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  }
  await scan(page, testInfo, "t28-assistant-drawer");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(ask).toBeFocused();
});

// Admin console: every tab, including the access-request queue. Needs an admin account.
for (const tab of ["Users", "Access requests", "Audit log", "Webhooks", "System"] as const) {
  test(`T28 admin console tab "${tab}" has no serious/critical axe violations`, async ({ page }, testInfo) => {
    await signInAsAdmin(page);
    await goClient(page, "/admin");
    await expect(page.getByRole("heading", { name: "Admin console" })).toBeVisible({ timeout: 20_000 });
    await page.getByRole("tab", { name: tab }).click();
    await page.waitForLoadState("networkidle", { timeout: 30_000 });
    await scan(page, testInfo, `t28-admin-${tab.toLowerCase().replace(/ /g, "-")}`);
  });
}

// Public access pages. The request form is submitted through the real UI (limit: 5 requests/hour/IP), which also gives the
// pending page a real request to show. The approve dialog is then opened by keyboard in the admin queue and cancelled.
test.describe.serial("T28 access pages", () => {
  const email = `a11y-visitor-${Date.now()}@example.com`;
  let ref = "";

  test("request form and pending page: axe clean, keyboard-reachable, visible focus", async ({ browser }, testInfo) => {
    const page = await (await browser.newContext()).newPage();
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /Sign in to TwinGrid/ })).toBeVisible({ timeout: 15_000 });
    const open = page.getByRole("button", { name: "Request viewer access" });
    await open.focus();
    await expectVisibleFocus(page, "Request viewer access button");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: /request/i }).first()).toBeVisible();
    await scan(page, testInfo, "t28-request-form");

    // Empty submit: the error summary must appear and take focus (keyboard users are told what is wrong).
    await page.getByRole("button", { name: "Send request" }).click();
    await scan(page, testInfo, "t28-request-form-errors");

    await page.getByLabel("Name").fill("A11y Visitor");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Purpose (optional)").fill("Accessibility sweep");
    await page.getByLabel("Purpose (optional)").press("Tab");
    await page.keyboard.press("Enter"); // the submit button must be next in the tab order
    await expect(page.getByRole("heading", { name: "Your access request" })).toBeVisible({ timeout: 20_000 });
    ref = ((await page.getByTestId("request-ref").textContent()) ?? "").trim();
    await scan(page, testInfo, "t28-pending-page");
  });

  test("activation page: incomplete link, password form and dead-link states are axe clean", async ({ page }, testInfo) => {
    await page.goto("/activate");
    await expect(page.getByRole("heading", { name: "Activation link problem" })).toBeVisible({ timeout: 15_000 });
    await scan(page, testInfo, "t28-activate-incomplete-link");

    // A goto that only changes the #fragment is not a page load, so the activation page would keep the empty-token state it
    // already rendered. Leave the page first so the link opens the way an emailed link does.
    await page.goto("about:blank");
    await page.goto(`/activate#token=${"A".repeat(43)}`); // well-formed but unknown: the real backend refuses it
    await expect(page.getByRole("heading", { name: "Set your password" })).toBeVisible({ timeout: 15_000 });
    await page.getByLabel("New password").fill("x");
    await page.getByLabel("Confirm password").fill("y");
    await page.getByRole("button", { name: "Activate access" }).click();
    await scan(page, testInfo, "t28-activate-client-errors");
    await page.getByLabel("New password").fill("correct horse battery staple");
    await page.getByLabel("Confirm password").fill("correct horse battery staple");
    await page.getByRole("button", { name: "Activate access" }).click();
    await expect(page.getByRole("heading", { name: "Activation link problem" })).toBeVisible({ timeout: 30_000 });
    await scan(page, testInfo, "t28-activate-dead-link");
  });

  test("admin approve dialog: axe clean, focus inside, Escape leaves no focus lost", async ({ page }, testInfo) => {
    test.skip(!ref, "needs the request made by the first test in this block");
    await signInAsAdmin(page);
    await goClient(page, "/admin");
    await page.getByRole("tab", { name: "Access requests" }).click();
    const card = page.locator("li", { hasText: ref });
    await expect(card).toBeVisible({ timeout: 20_000 });
    const approve = card.getByRole("button", { name: "Approve" });
    await approve.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toBeVisible();
    expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
    await scan(page, testInfo, "t28-admin-approve-dialog");
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    // focus must not be dropped on <body>: back on the opener (or the notices region)
    const active = await page.evaluate(() => (document.activeElement && document.activeElement !== document.body ? "element" : "body"));
    expect(active).toBe("element");
  });
});

// Reflow. 320 px wide (WCAG 1.4.10) and 640 x 512 as a stand-in for 200 % zoom (WCAG 1.4.4): no horizontal page scroll.
const REFLOW_VIEWPORTS = [
  { name: "320px", width: 320, height: 640 },
  { name: "zoom200-approx", width: 640, height: 512 },
] as const;

for (const vp of REFLOW_VIEWPORTS) {
  test(`T28 reflow (${vp.name}): sign-in, request form and activation pages need no horizontal scroll`, async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
    const page = await context.newPage();
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /Sign in to TwinGrid/ })).toBeVisible({ timeout: 15_000 });
    expect(await horizontalOverflow(page), "sign-in").toBeLessThanOrEqual(1);
    await page.getByRole("button", { name: "Request viewer access" }).click();
    await expect(page.getByRole("button", { name: "Send request" })).toBeVisible();
    expect(await horizontalOverflow(page), "request form").toBeLessThanOrEqual(1);
    await page.goto(`/activate#token=${"A".repeat(43)}`);
    await expect(page.getByRole("heading", { name: "Set your password" })).toBeVisible({ timeout: 15_000 });
    expect(await horizontalOverflow(page), "activation form").toBeLessThanOrEqual(1);
    await context.close();
  });

  test(`T28 reflow (${vp.name}): signed-in routes, measured and attached (soft: the shell is desktop-first)`, async ({ browser }, testInfo) => {
    const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
    const page = await context.newPage();
    await signIn(page, "viewer");
    const rows: Array<{ path: string; overflow_px: number }> = [{ path: "/", overflow_px: await horizontalOverflow(page) }];
    for (const route of [...ROUTES.slice(1), ...VIEWER_ROUTES]) {
      await goClient(page, route.path);
      await page.waitForLoadState("networkidle", { timeout: 30_000 });
      rows.push({ path: route.path, overflow_px: await horizontalOverflow(page) });
    }
    await testInfo.attach(`reflow-${vp.name}.json`, { body: JSON.stringify(rows, null, 2), contentType: "application/json" });
    for (const r of rows) expect.soft(r.overflow_px, `${r.path} overflows by ${r.overflow_px}px at ${vp.name}`).toBeLessThanOrEqual(1);
    await context.close();
  });
}

test("T28 reduced motion: access pages run no infinite animation", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Sign in to TwinGrid/ })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Request viewer access" }).click();
  await expect(page.getByRole("button", { name: "Send request" })).toBeVisible();
  const running = await page.evaluate(() =>
    document.getAnimations().filter((a) => a.playState === "running" && a.effect?.getTiming().iterations === Infinity).length
  );
  expect(running).toBe(0);
});
