import { defineConfig, devices } from "@playwright/test";

/**
 * Stage 22: browser smoke tests. They run against `npm run dev` and need NO
 * backend: with the API unreachable the app shows its "Connecting" state, which
 * is exactly what these tests tolerate. They check navigation and keyboard
 * behaviour, not live data.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://localhost:8080",
    trace: "retain-on-failure",
    // A fresh browser profile opens the first-run "Welcome to TwinGrid" modal after sign-in. A modal dialog hides the
    // page behind it from the accessibility tree, so getByRole("heading", { name: "Live Twin" }) never matches and
    // every signed-in test times out. Record the welcome as already seen (the same flag the app writes itself:
    // src/features/guided-tour/storage.ts). The dialog is covered by its own unit tests.
    storageState: {
      cookies: [],
      origins: [
        {
          origin: "http://localhost:8080",
          localStorage: [
            { name: "twingrid.tour.v1", value: JSON.stringify({ welcomeSeen: true, resumeStepId: null, completed: false }) },
          ],
        },
      ],
    },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1600, height: 900 } } }],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:8080",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
