import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * FE-03 accessibility harness. Runs axe on routes that need NO backend data (the sign-in screen).
 * Later tasks add their own routes/open panels here (FE-19 widens the coverage) instead of deferring a11y to the end.
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
