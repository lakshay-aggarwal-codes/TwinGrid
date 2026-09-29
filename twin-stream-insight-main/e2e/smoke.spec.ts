import { test, expect } from "@playwright/test";

test("load, open a panel, rotate to Analytics and back", async ({ page }) => {
  await page.goto("/");
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
  await page.goto("/legacy");
  await expect(page).toHaveURL(/\/analytics$/);
});

test("keyboard: arrow keys select racks and the selection is announced", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("group", { name: /3D facility view/ }).focus();

  await page.keyboard.press("ArrowRight");
  await expect(page.getByText("Selected Zone A, row 1, rack 1")).toBeAttached();

  await page.keyboard.press("ArrowRight");
  await expect(page.getByText("Selected Zone A, row 1, rack 2")).toBeAttached();

  await page.keyboard.press("Escape");
  await expect(page.getByText("No object selected")).toBeVisible();
});
