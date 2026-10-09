import { test, expect, type WebSocketRoute } from "@playwright/test";
import { signIn } from "./helpers";

/**
 * With the live socket dropped, no Live Twin surface keeps a current-looking value; when it is restored the feed is
 * live again only after a fresh valid frame.
 *
 * The ONLY interception here is the WebSocket TRANSPORT (`page.routeWebSocket`): frames from the real backend are
 * forwarded untouched, and the connection is closed on demand / refused while "dropped". That tests how the UI REACTS
 * to transport state. No data is fabricated, no REST endpoint is stubbed, auth is the real login.
 */
test("dropping the real socket leaves no current-looking value; restoring it brings the feed back", async ({ page }) => {
  test.setTimeout(180_000);

  let dropped = false;
  // Held in an object property: TypeScript does not narrow property writes made inside callbacks, whereas a bare
  // `let` assigned in the callback is narrowed to `null`/`never` at the use site.
  const conn: { current: { page: WebSocketRoute; server: WebSocketRoute } | null } = { current: null };
  await page.routeWebSocket(/\/ws\/live/, (ws) => {
    if (dropped) {
      void ws.close({ code: 1012, reason: "e2e: socket dropped" });
      return;
    }
    const server = ws.connectToServer(); // forwards frames both ways, unmodified
    conn.current = { page: ws, server };
  });

  await signIn(page);

  // Fresh: current readings from a real frame, live chip, the backend's origin.
  await expect(page.getByTestId("liveness")).toHaveAttribute("data-liveness", "live", { timeout: 45_000 });
  await expect(page.getByTestId("live-readings")).toHaveAttribute("data-readout", "current");
  await expect(page.getByTestId("origin-banner")).toContainText("Simulated");
  await page.screenshot({ path: "test-results/fe11-fresh.png" });

  // Drop: the open connection is closed and every reconnect attempt is refused.
  dropped = true;
  await conn.current?.server.close();
  await conn.current?.page.close({ code: 1012, reason: "e2e: socket dropped" });

  const liveness = page.getByTestId("liveness");
  await expect(liveness).not.toHaveAttribute("data-liveness", "live");
  await expect(liveness).toHaveAttribute("data-liveness", /^(disconnected|reconnecting|stale)$/);
  await expect(page.getByTestId("live-readings")).toHaveAttribute("data-readout", "last-known");
  await expect(page.getByTestId("last-known").first()).toContainText("Last known");
  await expect(page.getByTestId("feed-overlay")).toBeVisible();
  await expect(page.locator("[data-freshness='live']")).toHaveCount(0);
  await expect(page.locator("[data-readout='current']")).toHaveCount(0);
  await page.screenshot({ path: "test-results/fe11-dropped.png" });

  // It stays not-live while the socket stays down (no frame can have arrived).
  await page.waitForTimeout(8_000);
  await expect(liveness).not.toHaveAttribute("data-liveness", "live");
  await expect(page.locator("[data-readout='current']")).toHaveCount(0);

  // Restore: the next reconnect goes through to the real backend; live again only after a valid frame.
  dropped = false;
  await expect(liveness).toHaveAttribute("data-liveness", "live", { timeout: 90_000 });
  await expect(page.getByTestId("live-readings")).toHaveAttribute("data-readout", "current");
  await page.screenshot({ path: "test-results/fe11-restored.png" });
});
