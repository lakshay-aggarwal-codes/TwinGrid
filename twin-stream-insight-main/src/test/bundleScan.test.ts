/**
 * T4a acceptance: a PRODUCTION bundle contains no demo username/password.
 *
 * Builds the app for production with sentinel VITE_DEMO_* values (vite.config.ts
 * still requires them to be set, so this is the worst case: they are present in
 * the build environment) and greps every emitted file. A control value that the
 * app DOES inline (VITE_API_BASE_URL) must be found, which proves the scan can
 * see an inlined VITE_* value at all.
 */
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const DEMO_USER = "SENTINEL_DEMO_USER_8f3a";
const DEMO_PASS = "SENTINEL_DEMO_PASS_c91d";
const CONTROL = "sentinel-api.example.test";

function filesIn(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? filesIn(p) : [p];
  });
}

describe("production bundle", () => {
  let outDir = "";
  let corpus = "";

  beforeAll(() => {
    outDir = mkdtempSync(join(tmpdir(), "twingrid-bundle-"));
    const root = resolve(__dirname, "../..");
    execFileSync(process.execPath, [resolve(root, "node_modules/vite/bin/vite.js"), "build", "--outDir", outDir, "--emptyOutDir"], {
      cwd: root,
      stdio: "pipe",
      env: {
        ...process.env,
        NODE_ENV: "production",
        VITE_API_BASE_URL: `https://${CONTROL}`,
        VITE_DEMO_USERNAME: DEMO_USER,
        VITE_DEMO_PASSWORD: DEMO_PASS,
      },
    });
    corpus = filesIn(outDir)
      .filter((f) => /\.(js|css|html|map|json|txt)$/.test(f))
      .map((f) => readFileSync(f, "utf8"))
      .join("\n");
  }, 240_000);

  afterAll(() => {
    if (outDir) rmSync(outDir, { recursive: true, force: true });
  });

  it("scanned a real build (control value is present)", () => {
    expect(corpus.length).toBeGreaterThan(100_000);
    expect(corpus).toContain(CONTROL);
  });

  it("contains no demo username or password", () => {
    expect(corpus).not.toContain(DEMO_USER);
    expect(corpus).not.toContain(DEMO_PASS);
  });
});
