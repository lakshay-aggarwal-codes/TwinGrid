import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { test, expect, type Browser, type Page } from "@playwright/test";

/**
 * Task 31 (REL-002) browser drills. Real backend, nothing intercepted (same rule as the rest of e2e/**). Infrastructure drills
 * (database, Redis, mail transport, clean install) are shell scripts: scripts/drill_*.sh. The WebSocket drop / stale / reconnect
 * drill already exists as stale-surfaces.spec.ts and is NOT repeated here.
 *
 * Environment: E2E_ADMIN_USERNAME / E2E_ADMIN_PASSWORD. Token-expiry drill: backend started with DEMO_PUBLIC_ENABLED=true,
 * DEMO_SESSION_MINUTES=1 and a seeded `demo_viewer` (set E2E_DRILL_DEMO_SHORT=1 to say so; otherwise it is skipped, not passed).
 * The refresh drill creates one real access request (limit 5/hour/IP).
 *
 * Sequence-restart drill (R1 Task 11): stops and starts the REAL backend container, so it runs only with E2E_DRILL_RESTART=1
 * (needs Docker and the demo stack; otherwise it is skipped, not passed). Compose command: E2E_COMPOSE_ARGS (default
 * "--env-file .env.demo -f docker-compose.yml -f docker-compose.demo.yml"), service E2E_BACKEND_SERVICE (default "backend"),
 * run from the repo root. Account: E2E_VIEWER_USERNAME / E2E_VIEWER_PASSWORD.
 */
function need(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Set ${name} (see the header of e2e/drills.spec.ts).`);
  return v;
}

async function signInAdmin(browser: Browser): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Sign in to TwinGrid/ })).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("Username").fill(need("E2E_ADMIN_USERNAME"));
  await page.getByLabel("Password").fill(need("E2E_ADMIN_PASSWORD"));
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Live Twin" })).toBeVisible({ timeout: 30_000 });
  return page;
}

test("DRILL token expiry: a demo session ends with a notice and no data stays on screen", async ({ page }) => {
  test.skip(process.env.E2E_DRILL_DEMO_SHORT !== "1", "needs DEMO_SESSION_MINUTES=1 on the backend; set E2E_DRILL_DEMO_SHORT=1");
  test.setTimeout(150_000);
  await page.goto("/");
  await page.getByRole("button", { name: "Explore read-only demo" }).click();
  await expect(page.getByTestId("demo-banner")).toBeVisible({ timeout: 30_000 });
  // After the real expiry the app signs out by itself and says why.
  await expect(page.getByTestId("session-notice")).toContainText("Demo session ended", { timeout: 120_000 });
  await expect(page.getByRole("heading", { name: /Sign in to TwinGrid/ })).toBeVisible();
  await expect(page.getByTestId("demo-banner")).toHaveCount(0);
  await expect(page.getByTestId("live-readings")).toHaveCount(0);
});

test("DRILL refresh mid-approval: the visitor reloads while pending, the owner approves, the status is still right", async ({ page, browser }) => {
  test.setTimeout(180_000);
  const email = `drill-refresh-${Date.now()}@example.com`;
  await page.goto("/");
  await page.getByRole("button", { name: "Request viewer access" }).click();
  await page.getByLabel("Name").fill("Drill Visitor");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByRole("heading", { name: "Your access request" })).toBeVisible({ timeout: 20_000 });
  const ref = ((await page.getByTestId("request-ref").textContent()) ?? "").trim();
  expect(ref).toMatch(/^[A-Z2-7]{12}$/);

  await page.reload(); // sessionStorage ticket survives a reload in the same tab
  await expect(page.getByTestId("request-ref")).toHaveText(ref);
  await expect(page.getByTestId("request-status")).toHaveText("Awaiting decision");

  const admin = await signInAdmin(browser);
  await admin.getByRole("link", { name: "Admin" }).first().click();
  await admin.getByRole("tab", { name: "Access requests" }).click();
  const card = admin.locator("li", { hasText: ref });
  await expect(card).toBeVisible({ timeout: 20_000 });
  await card.getByRole("button", { name: "Approve" }).click();
  await admin.getByRole("button", { name: "Approve", exact: true }).last().click();
  // The default filter ("pending") hides a request once it is decided: show every status, as viewer-workflow.spec.ts does.
  await admin.getByTestId("access-filter").selectOption("all");
  await expect(card.getByText(/Approved, awaiting activation/).first()).toBeVisible({ timeout: 20_000 });

  await page.reload(); // reload again AFTER the decision: the page must show the decision, not a stale or invented state
  await expect(page.getByTestId("request-status")).toHaveText("Approved", { timeout: 60_000 });
});

test("DRILL dead links: malformed and unknown activation tokens give the same dead-link page, never a half-working form", async ({ browser }) => {
  for (const hash of ["", "#token=short", `#token=${"A".repeat(43)}`]) {
    const page = await (await browser.newContext()).newPage();
    await page.goto(`/activate${hash}`);
    if (hash === `#token=${"A".repeat(43)}`) {
      await page.getByLabel("New password").fill("correct horse battery staple");
      await page.getByLabel("Confirm password").fill("correct horse battery staple");
      await page.getByRole("button", { name: "Activate access" }).click();
    }
    await expect(page.getByRole("heading", { name: /Activation link problem|Set your password/ })).toBeVisible({ timeout: 20_000 });
    if (hash !== `#token=${"A".repeat(43)}`) await expect(page.getByRole("heading", { name: "Activation link problem" })).toBeVisible();
    else await expect(page.getByRole("heading", { name: "Activation link problem" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/Access activated/)).toHaveCount(0);
  }
});

test("DRILL empty/unknown data: an unknown run id shows an explicit not-found state, not an empty success", async ({ page }) => {
  need("E2E_VIEWER_USERNAME");
  const { signIn } = await import("./helpers");
  await signIn(page, "viewer", "/");
  await page.evaluate(() => {
    window.history.pushState({}, "", "/runs/drill-no-such-run");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(page.getByRole("heading", { level: 1, name: /^Run$/ })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/not found|no such run|unknown run|could not/i).first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/completed|succeeded/i)).toHaveCount(0);
});

/** Run `docker compose <args> <verb> <service>` from the repo root (the folder above the frontend package). */
function compose(verb: "stop" | "start"): void {
  const args = (process.env.E2E_COMPOSE_ARGS ?? "--env-file .env.demo -f docker-compose.yml -f docker-compose.demo.yml").split(/\s+/).filter(Boolean);
  execFileSync("docker", ["compose", ...args, verb, process.env.E2E_BACKEND_SERVICE ?? "backend"], {
    cwd: resolve(process.cwd(), ".."),
    stdio: "inherit",
    timeout: 120_000,
  });
}

test("DRILL sequence restart: the server's seq goes backwards after a real backend restart and the page recovers without a stale-looking value", async ({ page }) => {
  test.skip(process.env.E2E_DRILL_RESTART !== "1", "restarts the real backend container; set E2E_DRILL_RESTART=1 (needs Docker and the demo stack)");
  test.setTimeout(300_000);

  // OBSERVE the real frames: each is forwarded unchanged in both directions; only its `seq` is recorded.
  const seqs: number[] = [];
  await page.routeWebSocket(/\/ws\/live/, (ws) => {
    const server = ws.connectToServer();
    server.onMessage((msg) => {
      try {
        const frame = JSON.parse(typeof msg === "string" ? msg : msg.toString("utf8")) as { seq?: unknown };
        if (typeof frame.seq === "number") seqs.push(frame.seq);
      } catch {
        /* not JSON: forwarded as is */
      }
      ws.send(msg);
    });
    ws.onMessage((msg) => server.send(msg));
  });

  const { signIn } = await import("./helpers");
  await signIn(page, "viewer", "/");
  const liveness = page.getByTestId("liveness");
  await expect(liveness).toHaveAttribute("data-liveness", "live", { timeout: 45_000 });
  // Let the server counter climb, so that a restart (counter back to 1) is a visible regression and not a coincidence.
  await expect.poll(() => seqs[seqs.length - 1] ?? 0, { timeout: 150_000, intervals: [2_000] }).toBeGreaterThanOrEqual(20);
  const lastBefore = seqs[seqs.length - 1];
  const framesBefore = seqs.length;

  compose("stop");
  await expect(liveness).not.toHaveAttribute("data-liveness", "live", { timeout: 60_000 });
  await expect(page.getByTestId("live-readings")).toHaveAttribute("data-readout", "last-known");
  await expect(page.locator("[data-readout='current']")).toHaveCount(0);

  compose("start");
  await expect(liveness).toHaveAttribute("data-liveness", "live", { timeout: 180_000 });
  await expect(page.getByTestId("live-readings")).toHaveAttribute("data-readout", "current");
  await expect.poll(() => seqs.length - framesBefore, { timeout: 60_000, intervals: [2_000] }).toBeGreaterThanOrEqual(3);

  const after = seqs.slice(framesBefore);
  expect(after[0], `first seq after the restart (${after[0]}) must be below the last one before it (${lastBefore})`).toBeLessThan(lastBefore);
  const regressions = seqs.filter((v, i) => i > 0 && v < seqs[i - 1]).length;
  expect(regressions, `seq regressions seen: ${seqs.join(",")}`).toBe(1);
  expect(seqs.filter((v, i) => i > 0 && v === seqs[i - 1]), "duplicate adjacent seq values").toEqual([]);
  expect(after.every((v, i) => i === 0 || v > after[i - 1]), "seq must rise strictly after the restart").toBe(true);
  await page.screenshot({ path: "test-results/drill-seq-restart.png" });
});
