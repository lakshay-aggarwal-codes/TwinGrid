import { test, expect } from "@playwright/test";
import { signIn } from "./helpers";

/**
 * E2E-1 (roadmap Section 14): real backend + seeded viewer.
 * login -> Live Twin shows backend origin + freshness -> Simulation Lab returns a real /api/whatif result with Preview
 * provenance -> alerts list loads (empty is asserted as empty) -> logout.
 * Nothing is intercepted: the UI must agree with what the backend really answered.
 */
test("E2E-1: login, live origin + freshness, real what-if preview, alerts, logout", async ({ page }) => {
  test.setTimeout(180_000);
  const { username } = await signIn(page, "viewer");

  // 1. Live Twin: the BACKEND's origin ("Simulated") and a live freshness state, from a real frame.
  await expect(page.getByTestId("origin-banner")).toContainText("Simulated", { timeout: 45_000 });
  await expect(page.getByTestId("liveness")).toHaveAttribute("data-liveness", "live", { timeout: 45_000 });
  await expect(page.getByTestId("live-readings")).toHaveAttribute("data-readout", "current");
  await expect(page.getByRole("group", { name: "Account" })).toContainText(username);

  // 2. Simulation Lab: a real /api/whatif answer, shown as a Preview with its inputs.
  const whatif = page.waitForResponse((r) => r.url().includes("/api/whatif") && r.request().method() === "GET", { timeout: 60_000 });
  await page.getByRole("button", { name: "Simulation Lab" }).click();
  const whatifResponse = await whatif;
  expect(whatifResponse.status()).toBe(200);
  const lab = page.getByRole("complementary", { name: "Simulation Lab" });
  await expect(lab).toBeVisible();
  await expect(lab.getByText("Preview — simulated, constant inputs").first()).toBeVisible({ timeout: 30_000 });
  await expect(lab.getByText(/^Inputs: utilisation /).first()).toBeVisible();
  await page.getByRole("button", { name: "Close simulation lab" }).click();

  // 3. Alerts: the list must match what the backend really returned (empty is a valid, asserted state).
  const alertsRequest = page.waitForResponse((r) => r.url().includes("/api/alerts") && r.request().method() === "GET", { timeout: 60_000 });
  await page.getByRole("button", { name: "Incidents" }).click();
  const alertsResponse = await alertsRequest;
  expect(alertsResponse.status()).toBe(200);
  const alerts = (await alertsResponse.json()) as unknown[];
  const incidents = page.getByRole("complementary", { name: "Incidents" });
  await expect(incidents).toBeVisible();
  if (alerts.length === 0) {
    await expect(incidents.getByText(/No alerts recorded/)).toBeVisible();
  } else {
    await expect(incidents.getByRole("listitem")).toHaveCount(alerts.length);
  }
  await page.getByRole("button", { name: "Close incidents" }).click();

  // 4. Logout returns to the real sign-in screen.
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: /Sign in to TwinGrid/ })).toBeVisible();
});
