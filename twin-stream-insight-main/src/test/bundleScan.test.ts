/**
 * T4a acceptance: a PRODUCTION bundle contains no demo username/password.
 * FE-13: ...and a production build needs ONLY VITE_API_BASE_URL.
 *
 * 1. Builds for production with sentinel VITE_DEMO_* values present in the environment (the worst case: they are
 *    available to the build) and greps every emitted file. A control value that the app DOES inline
 *    (VITE_API_BASE_URL) must be found, which proves the scan can see an inlined VITE_* value at all.
 * 2. Builds again with the API base URL ONLY (no demo variables) and requires it to succeed.
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

/** Production build into a temp dir with exactly `extraEnv` as VITE_* configuration; returns every emitted text file joined. */
function buildCorpus(outDir: string, extraEnv: Record<string, string>): string {
  const root = resolve(__dirname, "../..");
  // Start from a clean slate: no inherited VITE_* variables from the developer's or CI's shell.
  const base = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith("VITE_")));
  execFileSync(process.execPath, [resolve(root, "node_modules/vite/bin/vite.js"), "build", "--outDir", outDir, "--emptyOutDir"], {
    cwd: root,
    stdio: "pipe",
    env: { ...base, NODE_ENV: "production", ...extraEnv },
  });
  return filesIn(outDir)
    .filter((f) => /\.(js|css|html|map|json|txt)$/.test(f))
    .map((f) => readFileSync(f, "utf8"))
    .join("\n");
}

describe("production bundle", () => {
  let outDir = "";
  let corpus = "";

  beforeAll(() => {
    outDir = mkdtempSync(join(tmpdir(), "twingrid-bundle-"));
    corpus = buildCorpus(outDir, {
      VITE_API_BASE_URL: `https://${CONTROL}`,
      VITE_DEMO_USERNAME: DEMO_USER,
      VITE_DEMO_PASSWORD: DEMO_PASS,
    });
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

describe("production build with only VITE_API_BASE_URL (FE-13)", () => {
  let outDir = "";
  let corpus = "";

  beforeAll(() => {
    outDir = mkdtempSync(join(tmpdir(), "twingrid-bundle-min-"));
    corpus = buildCorpus(outDir, { VITE_API_BASE_URL: `https://${CONTROL}` });
  }, 240_000);

  afterAll(() => {
    if (outDir) rmSync(outDir, { recursive: true, force: true });
  });

  it("succeeds without VITE_DEMO_USERNAME / VITE_DEMO_PASSWORD and targets the configured API", () => {
    expect(corpus.length).toBeGreaterThan(100_000);
    expect(corpus).toContain(CONTROL);
  });

  it("still contains no demo credentials and no sign-in bypass hint", () => {
    expect(corpus).not.toContain(DEMO_USER);
    expect(corpus).not.toContain(DEMO_PASS);
    expect(corpus).not.toMatch(/VITE_DEMO_(USERNAME|PASSWORD)/);
  });
});
