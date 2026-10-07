import { test, expect, type Page } from "@playwright/test";

/**
 * FE-06: with the socket killed, no Live Twin surface keeps a current-looking value.
 *
 * Only the WebSocket TRANSPORT is replaced (a fake that opens, delivers one frame, then closes). That is allowed here because the
 * test checks how the UI REACTS to transport state, not the data itself; no REST/data endpoint is stubbed, and the frame values
 * below are labels for that reaction, not telemetry. Auth endpoints are stubbed only to get past the sign-in screen (as in smoke.spec).
 */
const FAKE_ACCESS_TOKEN = `h.${Buffer.from(JSON.stringify({ exp: 4102444800 })).toString("base64url")}.s`;

async function stubAuth(page: Page) {
  await page.route("**/auth/login", (route) =>
    route.fulfill({ json: { access_token: FAKE_ACCESS_TOKEN, refresh_token: "r1", role: "viewer" } })
  );
  await page.route("**/auth/refresh", (route) =>
    route.fulfill({ json: { access_token: FAKE_ACCESS_TOKEN, refresh_token: "r2", role: "viewer" } })
  );
  await page.route("**/auth/logout", (route) => route.fulfill({ status: 204 }));
}

async function openSignedIn(page: Page) {
  await stubAuth(page);
  await page.goto("/");
  try {
    await page.getByRole("heading", { name: /Sign in to TwinGrid/ }).waitFor({ state: "visible", timeout: 5000 });
  } catch {
    return;
  }
  await page.getByLabel("Username").fill("alice");
  await page.getByLabel("Password").fill("correct-horse");
  await page.getByRole("button", { name: "Sign in" }).click();
}

/** Replace window.WebSocket for /ws/live: open, deliver one valid frame, and expose `window.__killSocket()`. */
async function installFakeSocket(page: Page) {
  await page.addInitScript(() => {
    const frame = {
      timestamp: "2026-01-01T12:35:00",
      server_utilisation: 0.5,
      outside_temp_C: 22,
      server_inlet_temp_C: 20,
      server_outlet_temp_C: 30,
      it_power_kw: 300,
      cooling_power_kw: 60,
      total_power_kw: 360,
      pue: 1.23,
      water_flow_lpm: 10,
      water_consumed_L: 5,
      wue: 0.456,
      humidity_pct: 50,
      water_pressure_bar: 3,
      cooling_mode: "hybrid",
      anomaly: 0,
      origin: "simulated",
      seq: 1,
      ts_ingest: "2026-10-06T14:03:21Z",
      sim_time: "2026-01-01T12:35:00",
      interval_s: 3,
    };
    const Real = window.WebSocket;
    class FakeSocket extends EventTarget {
      static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
      readyState = 0;
      onopen: ((e: Event) => void) | null = null;
      onmessage: ((e: MessageEvent) => void) | null = null;
      onclose: ((e: CloseEvent) => void) | null = null;
      onerror: ((e: Event) => void) | null = null;
      constructor(public url: string) {
        super();
        // Only the FIRST connection opens; later reconnect attempts stay "connecting", so the test observes the loss.
        if ((window as unknown as { __sock?: unknown }).__sock) return;
        (window as unknown as { __sock: FakeSocket }).__sock = this;
        setTimeout(() => {
          this.readyState = 1;
          this.onopen?.(new Event("open"));
          this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(frame) }));
        }, 50);
      }
      send() {}
      close() {}
    }
    (window as unknown as { __killSocket: () => void }).__killSocket = () => {
      const s = (window as unknown as { __sock?: FakeSocket }).__sock;
      if (!s) return;
      s.readyState = 3;
      s.onclose?.(new CloseEvent("close", { code: 1006 }));
    };
    window.WebSocket = function (url: string | URL, protocols?: string | string[]) {
      return String(url).includes("/ws/live") ? new FakeSocket(String(url)) : new Real(url, protocols);
    } as unknown as typeof WebSocket;
    Object.assign(window.WebSocket, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 });
  });
}

test("killing the socket leaves no current-looking value on the header, legend or inspector", async ({ page }) => {
  await installFakeSocket(page);
  await openSignedIn(page);

  // Fresh: current readings, Live chip, simulated badge.
  await expect(page.getByTestId("live-readings")).toHaveAttribute("data-readout", "current");
  await expect(page.getByTestId("liveness")).toHaveAttribute("data-liveness", "live");
  await expect(page.getByTestId("origin-banner")).toContainText("Simulated");
  await page.screenshot({ path: "test-results/fe06-fresh.png" });

  // Kill the transport.
  await page.evaluate(() => (window as unknown as { __killSocket: () => void }).__killSocket());

  const liveness = page.getByTestId("liveness");
  await expect(liveness).not.toHaveAttribute("data-liveness", "live");
  await expect(liveness).toHaveAttribute("data-liveness", /^(disconnected|reconnecting)$/);
  await expect(page.getByTestId("live-readings")).toHaveAttribute("data-readout", "last-known");
  await expect(page.getByTestId("last-known").first()).toContainText("Last known");
  await expect(page.getByTestId("feed-overlay")).toBeVisible();
  await expect(page.locator("[data-freshness='live']")).toHaveCount(0);
  await expect(page.locator("[data-readout='current']")).toHaveCount(0);
  await page.screenshot({ path: "test-results/fe06-disconnected.png" });
});
