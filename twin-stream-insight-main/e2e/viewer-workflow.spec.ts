import { test, expect, type APIResponse, type Browser, type Locator, type Page } from "@playwright/test";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { createServer, type Server, type Socket } from "node:net";
import { join } from "node:path";

/**
 * E2E-22 (viewer workflow), journeys J1-J4:
 *   J1 anonymous read-only demo        J2 a visitor asks for access      J3 the owner decides (desktop AND a 375 px phone)
 *   J4 the visitor opens the emailed link, sets a password and signs in as a read-only viewer.
 * Also: real SMTP capture, an outage followed by a resend, the public rate limits, and the demo's write controls.
 *
 * Same rules as the rest of e2e/**: NO page.route / fulfill / mock server / auth stub. Everything goes to a real backend.
 * The only test double is the SMTP sink below, and it stands in for the MAIL SERVER (the backend's real smtplib talks to it).
 *
 * Two backend modes (ACCESS_NOTIFY_BACKEND is one setting, so run the specs in two passes; tests are tagged in their names):
 *
 *   [file]  backend: ACCESS_NOTIFY_BACKEND=file ACCESS_NOTIFY_FILE_DIR=<dir> ACCESS_PUBLIC_BASE_URL=http://localhost:8080
 *           runner:  E2E_OUTBOX_DIR=<same dir>
 *           npx playwright test e2e/viewer-workflow.spec.ts --grep "\[file\]|\[demo\]"
 *
 *   [smtp]  backend: ACCESS_NOTIFY_BACKEND=smtp ACCESS_NOTIFY_SMTP_HOST=<host the backend uses to reach this machine,
 *                    e.g. host.docker.internal> ACCESS_NOTIFY_SMTP_PORT=<E2E_SMTP_PORT> ACCESS_NOTIFY_SMTP_TLS=none
 *                    ACCESS_NOTIFY_SMTP_USER=sink ACCESS_NOTIFY_SMTP_PASSWORD=sink ACCESS_NOTIFY_FROM=twingrid@example.com
 *                    ACCESS_NOTIFY_OWNER_EMAIL=owner@example.com ACCESS_PUBLIC_BASE_URL=http://localhost:8080
 *           runner:  E2E_SMTP_PORT=<port>   (this file starts and stops the sink on 0.0.0.0:<port>)
 *           npx playwright test e2e/viewer-workflow.spec.ts --grep "\[smtp\]"
 *
 *   [api]   needs the backend started with TRUST_PROXY_HEADERS=true (each test then uses its own X-Forwarded-For, so the
 *           per-IP windows of the other tests are untouched) and E2E_TRUST_PROXY=1 on the runner:
 *           npx playwright test e2e/viewer-workflow.spec.ts --grep "\[api\]"
 *
 * Always:  E2E_ADMIN_USERNAME / E2E_ADMIN_PASSWORD (an existing admin on the backend under test); optional E2E_API_BASE_URL
 *          (default http://localhost:8000). [demo] needs DEMO_PUBLIC_ENABLED=true and a seeded `demo_viewer` account.
 * The dev server must run WITHOUT VITE_DEMO_USERNAME/PASSWORD (otherwise the app signs in by itself).
 *
 * Limits on the REAL peer address, shared by every UI-driven test here: 5 access requests per hour (these specs use 3),
 * 3 public resends per hour (the outage test uses all 3 on purpose), 10 sign-ins per minute. The limiter is in memory:
 * restart the backend to reset the windows before a second run inside the same hour.
 */

const API = process.env.E2E_API_BASE_URL ?? "http://localhost:8000";
const PASSWORD = "correct horse battery staple 22";
const PHONE = { width: 375, height: 812 };
const ACTIVATION_LINK = /https?:\/\/[^\s"<>]+\/activate#token=[A-Za-z0-9_-]{43}/;

function need(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Set ${name} (see the header of e2e/viewer-workflow.spec.ts).`);
  return value;
}

// ----------------------------------------------------------------------------- mail: file outbox ([file] mode)

/** Decode quoted-printable well enough to read a link: soft line breaks removed, =XX bytes restored. */
function decodeQp(text: string): string {
  return text.replace(/=\r?\n/g, "").replace(/=([0-9A-Fa-f]{2})/g, (_m, hex: string) => String.fromCharCode(parseInt(hex, 16)));
}

/** Activation link from the newest `.eml` in the outbox addressed to `recipient`. */
function activationUrlFromOutbox(recipient: string): string {
  const dir = need("E2E_OUTBOX_DIR");
  const files = existsSync(dir)
    ? readdirSync(dir).filter((f) => f.includes("-activation-") && f.endsWith(".eml")).sort().reverse()
    : [];
  for (const file of files) {
    const text = decodeQp(readFileSync(join(dir, file), "utf8"));
    if (!text.toLowerCase().includes(recipient.toLowerCase())) continue;
    const match = text.match(ACTIVATION_LINK);
    if (match) return match[0];
  }
  throw new Error(`no activation mail for ${recipient} in ${dir}: is the backend using ACCESS_NOTIFY_BACKEND=file with this directory?`);
}

// ----------------------------------------------------------------------------- mail: SMTP sink ([smtp] mode)

interface Captured {
  to: string[];
  text: string;
}

/**
 * A minimal SMTP server for the backend's smtplib: plain text, AUTH PLAIN accepted, every message kept in memory.
 * stop() closes the listener AND open sockets, so the backend sees "connection refused" (an outage); start() brings it back.
 */
class SmtpSink {
  readonly mails: Captured[] = [];
  private server: Server | null = null;
  private readonly sockets = new Set<Socket>();

  private readonly port: number;

  constructor(port: number) {
    this.port = port;
  }

  start(): Promise<void> {
    return new Promise((resolve, reject) => {
      const server = createServer((socket) => this.session(socket));
      server.once("error", reject);
      server.listen(this.port, "0.0.0.0", () => {
        this.server = server;
        resolve();
      });
    });
  }

  stop(): Promise<void> {
    const server = this.server;
    this.server = null;
    for (const socket of this.sockets) socket.destroy();
    return new Promise((resolve) => (server ? server.close(() => resolve()) : resolve()));
  }

  to(address: string): Captured[] {
    return this.mails.filter((m) => m.to.includes(address.toLowerCase()));
  }

  activationLink(address: string): string | null {
    for (const mail of [...this.to(address)].reverse()) {
      const match = mail.text.match(ACTIVATION_LINK);
      if (match) return match[0];
    }
    return null;
  }

  private session(socket: Socket): void {
    this.sockets.add(socket);
    socket.on("close", () => this.sockets.delete(socket));
    socket.on("error", () => undefined);
    let buffer = "";
    let inData = false;
    let rcpt: string[] = [];
    const say = (line: string) => socket.write(`${line}\r\n`);
    say("220 sink ESMTP");
    socket.on("data", (chunk) => {
      buffer += chunk.toString("latin1");
      for (;;) {
        if (inData) {
          const end = buffer.indexOf("\r\n.\r\n");
          if (end < 0) return;
          const raw = buffer.slice(0, end).replace(/\r\n\.\./g, "\r\n.");
          buffer = buffer.slice(end + 5);
          inData = false;
          this.mails.push({ to: rcpt, text: decodeQp(raw) });
          rcpt = [];
          say("250 queued");
          continue;
        }
        const eol = buffer.indexOf("\r\n");
        if (eol < 0) return;
        const line = buffer.slice(0, eol);
        buffer = buffer.slice(eol + 2);
        const command = line.slice(0, 4).toUpperCase();
        if (command === "EHLO") socket.write("250-sink\r\n250 AUTH PLAIN\r\n");
        else if (command === "HELO") say("250 sink");
        else if (command === "AUTH") say("235 2.7.0 ok");
        else if (command === "MAIL") say("250 ok");
        else if (command === "RCPT") {
          const match = line.match(/<([^>]*)>/);
          if (match) rcpt.push(match[1].toLowerCase());
          say("250 ok");
        } else if (command === "DATA") {
          inData = true;
          say("354 go");
        } else if (command === "RSET" || command === "NOOP") say("250 ok");
        else if (command === "QUIT") {
          say("221 bye");
          socket.end();
          return;
        } else say("502 not implemented");
      }
    });
  }
}

async function startSink(): Promise<SmtpSink> {
  const sink = new SmtpSink(Number(need("E2E_SMTP_PORT")));
  await sink.start();
  return sink;
}

// ----------------------------------------------------------------------------- UI helpers

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

async function adminPage(browser: Browser, viewport?: { width: number; height: number }): Promise<Page> {
  const context = await browser.newContext(viewport ? { viewport, hasTouch: true, isMobile: true, deviceScaleFactor: 2 } : {});
  const page = await context.newPage();
  await signInWith(page, need("E2E_ADMIN_USERNAME"), need("E2E_ADMIN_PASSWORD"));
  return page;
}

/** J2: sign-in screen -> request form -> pending page. Returns the reference shown to the visitor. */
async function requestAccess(page: Page, email: string, purpose: string): Promise<string> {
  await page.goto("/");
  await page.getByRole("button", { name: "Request viewer access" }).click();
  await page.getByLabel("Name").fill("E2E Visitor");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Purpose (optional)").fill(purpose);
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByRole("heading", { name: "Your access request" })).toBeVisible({ timeout: 20_000 });
  await expect(page).toHaveURL(/\/access\/pending$/);
  await expect(page.getByTestId("request-status")).toHaveText("Awaiting decision", { timeout: 20_000 });
  const ref = (await page.getByTestId("request-ref").textContent())?.trim() ?? "";
  expect(ref).toMatch(/^[A-Z2-7]{12}$/);
  return ref;
}

/** Admin console -> Access requests, filter "All" (the default filter hides a request once it leaves "pending"). */
async function openQueue(admin: Page): Promise<void> {
  if (!admin.url().endsWith("/admin")) {
    const link = admin.getByRole("link", { name: "Admin" }).first();
    if (await link.isVisible()) await link.click();
    else await admin.goto("/admin");
  }
  await expect(admin.getByRole("heading", { name: "Admin console" })).toBeVisible({ timeout: 20_000 });
  await admin.getByRole("tab", { name: "Access requests" }).click();
  await admin.getByTestId("access-filter").selectOption("all");
}

/** Leave and re-enter the tab so the queue is fetched again, then show every status. */
async function refreshQueue(admin: Page): Promise<void> {
  await admin.getByRole("tab", { name: "Users" }).click();
  await openQueue(admin);
}

function cardFor(admin: Page, ref: string): Locator {
  return admin.getByTestId("access-list").locator("li", { hasText: ref });
}

/** J3 on any screen size: Approve -> confirm. Uses tap() on a touch context, click() otherwise. */
async function approve(admin: Page, ref: string, email: string, touch: boolean): Promise<void> {
  await openQueue(admin);
  const card = cardFor(admin, ref);
  await expect(card).toBeVisible({ timeout: 20_000 });
  await expect(card).toContainText(email);
  const approveButton = card.locator('[data-testid$="-approve"]');
  if (touch) await approveButton.tap();
  else await approveButton.click();
  const confirm = admin.getByTestId("access-confirm");
  await expect(confirm).toBeVisible();
  if (touch) await confirm.tap();
  else await confirm.click();
  await expect(card.getByText(/Approved, awaiting activation/).first()).toBeVisible({ timeout: 20_000 });
}

/** J4: open the emailed link in a fresh context, set a password. The token must leave the address bar at once. */
async function activate(browser: Browser, link: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await page.goto(link);
  await expect(page.getByRole("heading", { name: "Set your password" })).toBeVisible({ timeout: 20_000 });
  expect(page.url()).not.toContain("token");
  await page.getByLabel("New password").fill(PASSWORD);
  await page.getByLabel("Confirm password").fill(PASSWORD);
  await page.getByRole("button", { name: "Activate access" }).click();
  await expect(page.getByRole("heading", { name: "Access activated" })).toBeVisible({ timeout: 30_000 });
  return page;
}

async function expectReadOnlyViewer(browser: Browser, email: string): Promise<void> {
  const visitor = await (await browser.newContext()).newPage();
  await signInWith(visitor, email, PASSWORD);
  await expect(visitor.getByTestId("origin-banner")).toContainText("Simulated", { timeout: 45_000 });
  await expect(visitor.getByRole("group", { name: "Account" })).toContainText(email);
  await expect(visitor.getByRole("link", { name: "Admin" })).toHaveCount(0);
}

async function expectNoSideScroll(page: Page, where: string): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, `horizontal scrolling at 375 px (${where})`).toBeLessThanOrEqual(1);
}

async function expectTouchTarget(target: Locator, what: string): Promise<void> {
  const box = await target.boundingBox();
  expect(box, `${what} is not on screen`).not.toBeNull();
  expect(box!.width, `${what} is narrower than 44 px`).toBeGreaterThanOrEqual(43.5);
  expect(box!.height, `${what} is shorter than 44 px`).toBeGreaterThanOrEqual(43.5);
}

// ----------------------------------------------------------------------------- [file] J2-J4 on a desktop

test("E2E-22 [file] J2-J4: request access, owner approves, visitor activates and signs in read-only", async ({ page, browser }) => {
  test.setTimeout(240_000);
  const email = `e2e-viewer-${Date.now()}@example.com`;

  const ref = await requestAccess(page, email, "Automated viewer-workflow check");

  const admin = await adminPage(browser);
  await approve(admin, ref, email, false);

  // The visitor's pending page notices the decision by itself (polling) and says so.
  await expect(page.getByTestId("request-status")).toHaveText("Approved", { timeout: 60_000 });

  const link = activationUrlFromOutbox(email);
  await (await activate(browser, link)).close();

  // The link works once: opening it again shows the dead-link page, not a password form.
  const again = await (await browser.newContext()).newPage();
  await again.goto(link);
  await again.getByLabel("New password").fill(PASSWORD);
  await again.getByLabel("Confirm password").fill(PASSWORD);
  await again.getByRole("button", { name: "Activate access" }).click();
  await expect(again.getByRole("heading", { name: "Activation link problem" })).toBeVisible({ timeout: 30_000 });

  await expectReadOnlyViewer(browser, email);

  await refreshQueue(admin);
  await expect(cardFor(admin, ref).getByText(/Activated/).first()).toBeVisible({ timeout: 20_000 });
});

// ----------------------------------------------------------------------------- [smtp] J2-J4, owner decides on a phone

test("E2E-22 [smtp] J2-J4: owner approves on a 375 px phone, the mail arrives over SMTP, visitor activates", async ({ page, browser }) => {
  test.setTimeout(240_000);
  const sink = await startSink();
  try {
    const email = `e2e-phone-${Date.now()}@example.com`;
    const ref = await requestAccess(page, email, "Phone approval check");

    // The owner notification really went out over SMTP (to the configured owner address, not to the visitor).
    await expect.poll(() => sink.to("owner@example.com").some((m) => m.text.includes(ref)), { timeout: 30_000 }).toBe(true);
    expect(sink.to(email)).toHaveLength(0);

    // The owner works from a phone: 375 px wide, touch input.
    const phone = await adminPage(browser, PHONE);
    await expectNoSideScroll(phone, "after sign-in");
    await openQueue(phone);
    await expectNoSideScroll(phone, "access queue");
    const card = cardFor(phone, ref);
    await expect(card).toBeVisible({ timeout: 20_000 });
    await expectTouchTarget(card.locator('[data-testid$="-approve"]'), "Approve button");
    await expectTouchTarget(card.locator('[data-testid$="-reject"]'), "Reject button");
    await card.locator('[data-testid$="-approve"]').tap();
    const dialog = phone.getByTestId("access-dialog");
    await expect(dialog).toBeVisible();
    const box = await dialog.boundingBox();
    expect(box, "confirm dialog is not on screen").not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(-1);
    expect(box!.x + box!.width).toBeLessThanOrEqual(PHONE.width + 1);
    await expectTouchTarget(phone.getByTestId("access-confirm"), "Confirm button");
    await phone.getByTestId("access-confirm").tap();
    await expect(card.getByText(/Approved, awaiting activation/).first()).toBeVisible({ timeout: 20_000 });
    await expectNoSideScroll(phone, "after approval");

    // The visitor's page follows, and the activation mail arrives over SMTP.
    await expect(page.getByTestId("request-status")).toHaveText("Approved", { timeout: 60_000 });
    await expect.poll(() => sink.activationLink(email), { timeout: 30_000 }).not.toBeNull();
    await expect(async () => {
      await refreshQueue(phone);
      await expect(cardFor(phone, ref).locator('[data-testid$="-notify"]')).toContainText("Email sent");
    }).toPass({ timeout: 60_000 });

    await (await activate(browser, sink.activationLink(email)!)).close();
    await expectReadOnlyViewer(browser, email);
  } finally {
    await sink.stop();
  }
});

// ----------------------------------------------------------------------------- [smtp] outage, then resend; rate-limited resend

test("E2E-22 [smtp] a mail outage does not block approval; the resend reaches the visitor; the public resend is rate limited", async ({
  page,
  browser,
  request,
}) => {
  test.setTimeout(300_000);
  const sink = await startSink();
  try {
    const email = `e2e-outage-${Date.now()}@example.com`;
    const ref = await requestAccess(page, email, "Outage and resend check");
    await expect.poll(() => sink.to("owner@example.com").some((m) => m.text.includes(ref)), { timeout: 30_000 }).toBe(true);

    // OUTAGE: the mail server goes away, then the owner approves.
    await sink.stop();
    const admin = await adminPage(browser);
    await openQueue(admin);
    const card = cardFor(admin, ref);
    await expect(card).toBeVisible({ timeout: 20_000 });
    await card.locator('[data-testid$="-approve"]').click();
    await admin.getByTestId("access-confirm").click();
    await expect(card.getByText(/Approved, awaiting activation/).first()).toBeVisible({ timeout: 20_000 });

    // The decision stands, the row says the email FAILED (never "sent"), and no link was delivered.
    await expect(page.getByTestId("request-status")).toHaveText("Approved", { timeout: 60_000 });
    await expect(async () => {
      await refreshQueue(admin);
      await expect(cardFor(admin, ref).locator('[data-testid$="-notify"]')).toContainText("Email failed");
    }).toPass({ timeout: 60_000 });
    await expect(cardFor(admin, ref).locator('[data-testid$="-resend-activation"]')).toBeVisible();
    expect(sink.activationLink(email)).toBeNull();

    // RECOVERY: the server is back; the owner resends; the link arrives and the row says "sent".
    await sink.start();
    await cardFor(admin, ref).locator('[data-testid$="-resend-activation"]').click();
    await expect(admin.getByTestId("access-notice")).toContainText(`A new activation link is being sent for ${ref}.`);
    await expect.poll(() => sink.activationLink(email), { timeout: 30_000 }).not.toBeNull();
    await expect(async () => {
      await refreshQueue(admin);
      await expect(cardFor(admin, ref).locator('[data-testid$="-notify"]')).toContainText("Email sent");
    }).toPass({ timeout: 60_000 });

    // RATE LIMIT in the UI: three public resends are allowed per hour per address; the fourth says so and stays calm.
    for (let i = 0; i < 3; i++) {
      await request.post(`${API}/api/access-requests/resend-activation`, { data: { ref: "AAAAAAAAAAAA", status_token: "x" } });
    }
    await page.getByRole("button", { name: "Resend activation link" }).click();
    await expect(page.getByTestId("resend-note")).toHaveText("Too many attempts. Wait a minute and try again.", { timeout: 20_000 });

    // The link the owner's resend produced still works.
    await (await activate(browser, sink.activationLink(email)!)).close();
    await expectReadOnlyViewer(browser, email);
  } finally {
    await sink.stop();
  }
});

// ----------------------------------------------------------------------------- [api] public limits

test("E2E-22 [api] the public access routes answer 429 with Retry-After when their limits are used up", async ({ request }) => {
  expect(process.env.E2E_TRUST_PROXY, "start the backend with TRUST_PROXY_HEADERS=true and set E2E_TRUST_PROXY=1 (see header)").toBe("1");
  // A fresh last octet per run (the limiters remember an address for a day). Clock-derived, not random: e2e/** is gated against Math.random.
  const octet = () => 1 + (Date.now() % 250);
  const post = (path: string, data: unknown, ip: string) =>
    request.post(`${API}${path}`, { data, headers: { "X-Forwarded-For": ip } });

  // 3 requests per address per day: the fourth is refused.
  const email = `e2e-limit-${Date.now()}@example.com`;
  const submitIp = `203.0.113.${octet()}`;
  const submitted: APIResponse[] = [];
  for (let i = 0; i < 4; i++) {
    submitted.push(await post("/api/access-requests", { name: "E2E Limit", email, purpose: "rate limit check" }, submitIp));
  }
  expect(submitted.map((r) => r.status())).toEqual([202, 202, 202, 429]);
  expect(submitted[3].headers()["retry-after"]).toMatch(/^\d+$/);

  // 3 public resends per hour per IP: the fourth is refused (the IP window is checked before the body is read).
  const resendIp = `198.51.100.${octet()}`;
  const resent: APIResponse[] = [];
  for (let i = 0; i < 4; i++) {
    resent.push(await post("/api/access-requests/resend-activation", { ref: "AAAAAAAAAAAA", status_token: "x" }, resendIp));
  }
  expect(resent.map((r) => r.status())).toEqual([202, 202, 202, 429]);
  expect(resent[3].headers()["retry-after"]).toMatch(/^\d+$/);
});

// ----------------------------------------------------------------------------- [demo] J1 and its write controls

test("E2E-22 [demo] J1: the read-only demo is labelled and needs no account", async ({ page }) => {
  test.setTimeout(120_000); // the first load of the 3D page compiles it in the dev server
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

test("E2E-22 [demo] the demo session is refused on every write route and still gets reads and the assistant", async ({ page, request }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Sign in to TwinGrid/ })).toBeVisible({ timeout: 15_000 });
  // Observe the real session response (no interception): its token is what the app itself uses.
  const session = page.waitForResponse((r) => r.url().includes("/auth/demo-session") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Explore read-only demo" }).click();
  const token = ((await (await session).json()) as { access_token: string }).access_token;
  await expect(page.getByTestId("demo-banner")).toContainText("Read-only demo", { timeout: 30_000 });
  const headers = { Authorization: `Bearer ${token}` };

  const writes: Array<[string, string]> = [
    ["POST", "/api/runs"],
    ["POST", "/api/optimize"],
    ["POST", "/api/webhooks"],
    ["DELETE", "/api/webhooks"],
    ["POST", "/api/alerts/1/acknowledge"],
    ["POST", "/api/maintenance/work-orders"],
    ["POST", "/api/optimizer/proposals"],
    ["POST", "/api/admin/users/1/role"],
    ["PUT", "/api/admin/webhooks/1"],
  ];
  for (const [method, path] of writes) {
    const response = await request.fetch(`${API}${path}`, { method, headers, data: {} });
    expect(response.status(), `${method} ${path}`).toBe(403);
    expect(((await response.json()) as { type?: string }).type, `${method} ${path}`).toBe("urn:twingrid:error:demo_read_only");
  }

  expect((await request.get(`${API}/api/state`, { headers })).status()).toBe(200); // reads stay open
  const ask = await request.post(`${API}/api/copilot/ask`, {
    headers,
    data: { question: "What does the temperature signal mean?", context: { kind: "general" } },
  });
  expect(ask.status(), "the assistant stays open to the demo").toBe(200);
});
