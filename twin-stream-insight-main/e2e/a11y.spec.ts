import { test, expect, type Page, type TestInfo } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { signIn } from "./helpers";

/**
 * FE-03 accessibility harness. Runs axe on routes that need NO backend data (the sign-in screen).
 * Later tasks add their own routes/open panels here (FE-19 widens the coverage) instead of deferring a11y to the end.
 * FE-19: the signed-in sections below cover every route and every open panel (0 serious/critical) and the Section 13
 * keyboard flows. They need the real backend + seeded E2E_VIEWER_* account (see helpers.ts); the login tests above do not.
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
  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  await testInfo.attach(`axe-${label}.json`, { body: JSON.stringify(results.violations, null, 2), contentType: "application/json" });
  const blocking = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(
    blocking,
    JSON.stringify(blocking.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.map((n) => n.target) })), null, 2)
  ).toEqual([]);
}

const ROUTES: ReadonlyArray<{ path: string; heading: RegExp }> = [
  { path: "/", heading: /^Live Twin$/ },
  { path: "/analytics", heading: /Analytics/ },
  { path: "/runs", heading: /./ },
];

for (const colorScheme of ["light", "dark"] as const) {
  for (const route of ROUTES) {
    test(`route ${route.path} has no serious/critical axe violations (${colorScheme})`, async ({ page }, testInfo) => {
      await page.emulateMedia({ colorScheme });
      await signIn(page, "viewer", route.path);
      await expect(page.getByRole("heading", { name: route.heading }).first()).toBeVisible();
      await scan(page, testInfo, `route${route.path.replace(/\//g, "-") || "-root"}-${colorScheme}`);
    });
  }
}

test("analytics: every chart has a title, a text summary and a data table", async ({ page }, testInfo) => {
  await signIn(page, "viewer", "/analytics");
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
