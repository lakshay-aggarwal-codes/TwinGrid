import { test, expect } from "@playwright/test";
import { credentials, signIn } from "./helpers";

// FE-11: these run against the REAL backend through the real login screen (see helpers.ts). No auth or data stubs.

test("load, open a panel, rotate to Analytics and back", async ({ page }) => {
  await signIn(page);
  await expect(page.getByRole("heading", { name: "Live Twin" })).toBeVisible();
  await expect(page).toHaveTitle(/Live Twin/);

  await page.getByRole("button", { name: "Simulation Lab" }).click();
  await expect(page.getByRole("complementary", { name: "Simulation Lab" })).toBeVisible();

  await page.getByRole("link", { name: "Analytics" }).click();
  await expect(page).toHaveURL(/\/analytics$/);
  await expect(page.getByRole("heading", { name: /Analytics/ })).toBeVisible();
  await expect(page).toHaveTitle(/Analytics/);

  await page.getByRole("link", { name: "Live Twin" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Live Twin" })).toBeVisible();
  await expect(page).toHaveTitle(/Live Twin/);
});

test("the old /legacy address redirects to /analytics", async ({ page }) => {
  await signIn(page, "viewer", "/legacy");
  await expect(page).toHaveURL(/\/analytics$/);
});

test("keyboard: arrow keys select racks and the selection is announced", async ({ page }) => {
  await signIn(page);
  await page.getByRole("group", { name: /3D facility view/ }).focus();

  await page.keyboard.press("ArrowRight");
  await expect(page.getByText("Selected Zone A, row 1, rack 1")).toBeAttached();

  await page.keyboard.press("ArrowRight");
  await expect(page.getByText("Selected Zone A, row 1, rack 2")).toBeAttached();

  await page.keyboard.press("Escape");
  await expect(page.getByText("No object selected")).toBeVisible();
});

test("sign-in: a wrong password is refused by the backend; the right one opens the app; sign out returns to the login screen", async ({ page }) => {
  const { username, password } = credentials("viewer");
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Sign in to TwinGrid/ })).toBeVisible();

  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(`${password}-wrong`);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("Invalid username or password");

  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Live Twin" })).toBeVisible();
  await expect(page.getByRole("group", { name: "Account" })).toContainText(username);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: /Sign in to TwinGrid/ })).toBeVisible();
});
