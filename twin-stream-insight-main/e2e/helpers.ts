import { expect, type Page } from "@playwright/test";

/**
 * FE-11: real-backend E2E helpers.
 *
 * Rules for everything in e2e/**: NO `page.route` / `context.route` / `fulfill` / mock server / auth stub. The sign-in
 * goes through the real login screen against a real backend with seeded accounts. The one permitted interception is
 * dropping/restoring the WebSocket (`page.routeWebSocket`, see stale-surfaces.spec.ts), to test how the UI REACTS.
 * `page.waitForResponse` only OBSERVES real traffic.
 */
export type Role = "viewer" | "operator";

export function credentials(role: Role): { username: string; password: string } {
  const prefix = `E2E_${role.toUpperCase()}`;
  const username = process.env[`${prefix}_USERNAME`];
  const password = process.env[`${prefix}_PASSWORD`];
  if (!username || !password) {
    throw new Error(
      `Set ${prefix}_USERNAME and ${prefix}_PASSWORD to an account that exists on the backend under test (CI seeds them via POST /auth/register).`
    );
  }
  return { username, password };
}

/**
 * Sign in through the real login screen. The dev server must run WITHOUT VITE_DEMO_USERNAME/PASSWORD (otherwise
 * the app signs in by itself and this helper fails loudly instead of testing nothing). The backend limits sign-ins to
 * 10/minute per IP, so a 429 is waited out (bounded) rather than treated as a failure.
 */
export async function signIn(page: Page, role: Role = "viewer", path = "/"): Promise<{ username: string }> {
  const { username, password } = credentials(role);
  await page.goto(path);
  const heading = page.getByRole("heading", { name: /Sign in to TwinGrid/ });
  await expect(heading, "no sign-in screen: is VITE_DEMO_USERNAME set for this dev server?").toBeVisible({ timeout: 15_000 });

  for (let attempt = 1; attempt <= 5; attempt++) {
    await page.getByLabel("Username").fill(username);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();

    const live = page.getByRole("heading", { name: "Live Twin" });
    const alert = page.getByRole("alert");
    await expect(live.or(alert).first()).toBeVisible({ timeout: 20_000 });
    if (await live.isVisible()) return { username };

    const text = (await alert.first().textContent()) ?? "";
    if (/too many/i.test(text) && attempt < 5) {
      await page.waitForTimeout(15_000); // login limiter: 10 per minute per IP
      continue;
    }
    throw new Error(`sign-in failed for the seeded ${role} account: ${text.trim()}`);
  }
  throw new Error("sign-in did not succeed");
}
