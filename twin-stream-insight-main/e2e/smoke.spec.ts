import { test, expect, type Page } from "@playwright/test";

// The app now sits behind a sign-in screen. These tests run against the dev server
// with no backend, so the auth endpoints are stubbed: a fake JWT that expires far in
// the future is returned for a successful login, and /auth/login answers 401 for the
// password "wrong".
const FAKE_ACCESS_TOKEN = `h.${Buffer.from(JSON.stringify({ exp: 4102444800 })).toString("base64url")}.s`;

async function stubAuth(page: Page) {
  await page.route("**/auth/login", async (route) => {
    const { password } = route.request().postDataJSON() as { password: string };
    if (password === "wrong") return route.fulfill({ status: 401, json: { detail: "Invalid credentials" } });
    return route.fulfill({ json: { access_token: FAKE_ACCESS_TOKEN, refresh_token: "r1", role: "viewer" } });
  });
  await page.route("**/auth/refresh", (route) =>
    route.fulfill({ json: { access_token: FAKE_ACCESS_TOKEN, refresh_token: "r2", role: "viewer" } })
  );
  await page.route("**/auth/logout", (route) => route.fulfill({ status: 204 }));
}

/** Open `path` and get past the sign-in screen (a dev server with VITE_DEMO_* set may sign in by itself). */
async function openSignedIn(page: Page, path = "/") {
  await stubAuth(page);
  await page.goto(path);
  const loginHeading = page.getByRole("heading", { name: /Sign in to TwinGrid/ });
  try {
    await loginHeading.waitFor({ state: "visible", timeout: 5000 });
  } catch {
    return; // no sign-in screen appeared (e.g. dev auto-login with VITE_DEMO_*): already in
  }
  await page.getByLabel("Username").fill("alice");
  await page.getByLabel("Password").fill("correct-horse");
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("load, open a panel, rotate to Analytics and back", async ({ page }) => {
  await openSignedIn(page);
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
  await openSignedIn(page, "/legacy");
  await expect(page).toHaveURL(/\/analytics$/);
});

test("keyboard: arrow keys select racks and the selection is announced", async ({ page }) => {
  await openSignedIn(page);
  await page.getByRole("group", { name: /3D facility view/ }).focus();

  await page.keyboard.press("ArrowRight");
  await expect(page.getByText("Selected Zone A, row 1, rack 1")).toBeAttached();

  await page.keyboard.press("ArrowRight");
  await expect(page.getByText("Selected Zone A, row 1, rack 2")).toBeAttached();

  await page.keyboard.press("Escape");
  await expect(page.getByText("No object selected")).toBeVisible();
});

test("sign-in: wrong password shows an error; the right one opens the app; sign out returns to the login screen", async ({ page }) => {
  await stubAuth(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Sign in to TwinGrid/ })).toBeVisible();

  await page.getByLabel("Username").fill("alice");
  await page.getByLabel("Password").fill("wrong");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("Invalid username or password");

  await page.getByLabel("Password").fill("correct-horse");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Live Twin" })).toBeVisible();
  await expect(page.getByRole("group", { name: "Account" })).toContainText("alice");

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: /Sign in to TwinGrid/ })).toBeVisible();
});
