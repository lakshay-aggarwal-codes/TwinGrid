import { test, expect, type Browser, type Page } from "@playwright/test";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

/**
 * E2E-22 (viewer workflow): a visitor asks for access in the real UI, the owner approves in the real admin console, the
 * visitor opens the emailed link, sets a password and signs in as a read-only viewer. A second test covers the demo.
 *
 * Same rules as the rest of e2e/**: NO page.route / fulfill / mock server / auth stub. Everything goes to a real backend.
 *
 * Environment (the backend and this runner must share the outbox directory):
 *   E2E_ADMIN_USERNAME / E2E_ADMIN_PASSWORD   an existing admin account on the backend under test
 *   E2E_OUTBOX_DIR                            the backend's ACCESS_NOTIFY_FILE_DIR (backend runs ACCESS_NOTIFY_BACKEND=file,
 *                                             ACCESS_PUBLIC_BASE_URL=http://localhost:8080, ACCESS_TOKEN_PEPPER set)
 *   Demo test: backend DEMO_PUBLIC_ENABLED=true and a seeded `demo_viewer` account. Set E2E_DEMO_DISABLED=1 to skip it.
 * The dev server must run WITHOUT VITE_DEMO_USERNAME/PASSWORD (otherwise the app signs in by itself).
 * Limits to respect: 5 access requests per hour per IP; 10 sign-ins per minute per IP.
 */

function need(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Set ${name} (see the header of e2e/viewer-workflow.spec.ts).`);
  return value;
}

const PASSWORD = "correct horse battery staple 22";

/** Newest `.eml` of one kind in the outbox, as plain text (quoted-printable soft line breaks removed). */
function latestMail(kind: string): string {
  const dir = need("E2E_OUTBOX_DIR");
  const files = existsSync(dir) ? readdirSync(dir).filter((f) => f.includes(`-${kind}-`) && f.endsWith(".eml")).sort() : [];
  if (files.length === 0) throw new Error(`no '${kind}' mail in ${dir}: is the backend using ACCESS_NOTIFY_BACKEND=file with this directory?`);
  return readFileSync(join(dir, files[files.length - 1]), "utf8").replace(/=\r?\n/g, "").replace(/=3D/g, "=");
}

function activationUrl(): string {
  const match = latestMail("activation").match(/https?:\/\/[^\s"<>]+\/activate#token=[A-Za-z0-9_-]{43}/);
  if (!match) throw new Error("the activation mail has no link of the form <base>/activate#token=<43 chars>");
  return match[0];
}

async function signInWith(page: Page, username: string, password: string): Promise<void> {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /Sign in to TwinGrid/ }),
    "no sign-in screen: is VITE_DEMO_USERNAME set for this dev server?"
  ).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Live Twin" })).toBeVisible({ timeout: 30_000 });
}

async function adminPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInWith(page, need("E2E_ADMIN_USERNAME"), need("E2E_ADMIN_PASSWORD"));
  return page;
}

test("E2E-22: request access, owner approves, visitor activates and signs in read-only", async ({ page, browser }) => {
  test.setTimeout(240_000);
  const email = `e2e-viewer-${Date.now()}@example.com`;

  // 1. Visitor: sign-in screen -> request form -> pending page with a reference and "Awaiting decision".
  await page.goto("/");
  await page.getByRole("button", { name: "Request viewer access" }).click();
  await page.getByLabel("Name").fill("E2E Visitor");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Purpose (optional)").fill("Automated viewer-workflow check");
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByRole("heading", { name: "Your access request" })).toBeVisible({ timeout: 20_000 });
  await expect(page).toHaveURL(/\/access\/pending$/);
  await expect(page.getByTestId("request-status")).toHaveText("Awaiting decision");
  const ref = (await page.getByTestId("request-ref").textContent())?.trim() ?? "";
  expect(ref).toMatch(/^[A-Z2-7]{12}$/);

  // 2. Owner (separate browser context, real admin sign-in): the request is in the queue; approve it.
  const admin = await adminPage(browser);
  await admin.getByRole("link", { name: "Admin" }).first().click();
  await expect(admin.getByRole("heading", { name: "Admin console" })).toBeVisible();
  await admin.getByRole("tab", { name: "Access requests" }).click();
  const card = admin.locator("li", { hasText: ref });
  await expect(card).toBeVisible({ timeout: 20_000 });
  await expect(card).toContainText(email);
  await card.getByRole("button", { name: "Approve" }).click();
  await admin.getByRole("button", { name: "Approve", exact: true }).last().click(); // confirm dialog
  await expect(card.getByText(/Approved, awaiting activation/).first()).toBeVisible({ timeout: 20_000 });

  // 3. Visitor's pending page notices the decision by itself (polling) and says so.
  await expect(page.getByTestId("request-status")).toHaveText("Approved", { timeout: 60_000 });

  // 4. The emailed link: open it in a fresh tab. The token must leave the address bar at once.
  const link = activationUrl();
  const activate = await (await browser.newContext()).newPage();
  await activate.goto(link);
  await expect(activate.getByRole("heading", { name: "Set your password" })).toBeVisible({ timeout: 20_000 });
  expect(activate.url()).not.toContain("token");
  await activate.getByLabel("New password").fill(PASSWORD);
  await activate.getByLabel("Confirm password").fill(PASSWORD);
  await activate.getByRole("button", { name: "Activate access" }).click();
  await expect(activate.getByRole("heading", { name: "Access activated" })).toBeVisible({ timeout: 30_000 });

  // 5. The link works once: opening it again shows the dead-link page, not a password form.
  const again = await (await browser.newContext()).newPage();
  await again.goto(link);
  await again.getByLabel("New password").fill(PASSWORD);
  await again.getByLabel("Confirm password").fill(PASSWORD);
  await again.getByRole("button", { name: "Activate access" }).click();
  await expect(again.getByRole("heading", { name: "Activation link problem" })).toBeVisible({ timeout: 30_000 });

  // 6. Sign in with the approved address. Viewer: live twin yes, admin console no.
  const visitor = await (await browser.newContext()).newPage();
  await signInWith(visitor, email, PASSWORD);
  await expect(visitor.getByTestId("origin-banner")).toContainText("Simulated", { timeout: 45_000 });
  await expect(visitor.getByRole("group", { name: "Account" })).toContainText(email);
  await expect(visitor.getByRole("link", { name: "Admin" })).toHaveCount(0);

  // 7. Owner's queue now shows the request as activated.
  await admin.getByRole("tab", { name: "Users" }).click(); // leave and re-enter the tab so the queue is fetched again
  await admin.getByRole("tab", { name: "Access requests" }).click();
  await expect(admin.locator("li", { hasText: ref }).getByText(/Activated/).first()).toBeVisible({ timeout: 20_000 });
});

test("E2E-22: the read-only demo is labelled and needs no account", async ({ page }) => {
  test.skip(process.env.E2E_DEMO_DISABLED === "1", "E2E_DEMO_DISABLED=1: this backend has the demo switched off");
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Sign in to TwinGrid/ })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Explore read-only demo" }).click();
  await expect(page.getByTestId("demo-banner")).toContainText("Read-only demo", { timeout: 30_000 });
  await expect(page.getByTestId("demo-banner")).toContainText("Simulated data");
  await expect(page.getByRole("heading", { name: "Live Twin" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("origin-banner")).toContainText("Simulated", { timeout: 45_000 });
  await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);
});
