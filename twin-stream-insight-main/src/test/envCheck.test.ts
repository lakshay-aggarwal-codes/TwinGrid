/** FE-13: the production environment check in vite.config.ts requires ONLY the API base URL. */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import ts from "typescript";

/**
 * vite.config.ts cannot be imported under vitest (it loads vite/esbuild, which refuses jsdom, and the shared test
 * setup needs a DOM). So this test takes the REAL env-check source out of the file, transpiles it with the project's
 * TypeScript and runs it: what is tested is the code that runs at build time, not a copy.
 */
const source = readFileSync(resolve(__dirname, "../../vite.config.ts"), "utf8");
const start = source.indexOf("export const REQUIRED_PRODUCTION_ENV");
const end = source.indexOf("// https://vitejs.dev/config/");
if (start < 0 || end < start) throw new Error("env-check block not found in vite.config.ts");
const js = ts.transpileModule(source.slice(start, end), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
const mod: { exports: Record<string, unknown> } = { exports: {} };
new Function("exports", "module", js)(mod.exports, mod);
const REQUIRED_PRODUCTION_ENV = mod.exports.REQUIRED_PRODUCTION_ENV as readonly string[];
const checkProductionEnv = mod.exports.checkProductionEnv as (env: Record<string, string>) => { errors: string[]; warnings: string[] };

const API = "https://api.example.org";

describe("checkProductionEnv", () => {
  it("requires exactly VITE_API_BASE_URL", () => {
    expect([...REQUIRED_PRODUCTION_ENV]).toEqual(["VITE_API_BASE_URL"]);
  });

  it("passes with only the API URL (no demo variables), warning only about the missing error-report URL", () => {
    const r = checkProductionEnv({ VITE_API_BASE_URL: API });
    expect(r.errors).toEqual([]);
    expect(r.warnings).toHaveLength(1);
    expect(r.warnings[0]).toMatch(/VITE_ERROR_REPORT_URL/);
  });

  it("is fully quiet when the error-report URL is set too", () => {
    expect(checkProductionEnv({ VITE_API_BASE_URL: API, VITE_ERROR_REPORT_URL: "https://logs.example.org" })).toEqual({ errors: [], warnings: [] });
  });

  it.each([[{}], [{ VITE_API_BASE_URL: "" }], [{ VITE_API_BASE_URL: "   " }]])("fails without a usable API URL: %j", (env) => {
    expect(checkProductionEnv(env as Record<string, string>).errors).toEqual(["VITE_API_BASE_URL is not set"]);
  });

  it.each([["http://localhost:8000"], ["https://localhost"], ["http://127.0.0.1:8000"], ["http://[::1]:8000"]])("rejects a localhost target: %s", (url) => {
    expect(checkProductionEnv({ VITE_API_BASE_URL: url }).errors[0]).toMatch(/must not target localhost/);
  });

  it("warns (not errors) on plain http to a real host", () => {
    const r = checkProductionEnv({ VITE_API_BASE_URL: "http://api.example.org" });
    expect(r.errors).toEqual([]);
    expect(r.warnings.join(" ")).toMatch(/plain http/);
  });

  it("demo credentials are not required, and when present are warned about as ignored (never an error)", () => {
    const r = checkProductionEnv({ VITE_API_BASE_URL: API, VITE_DEMO_USERNAME: "u", VITE_DEMO_PASSWORD: "p", VITE_ERROR_REPORT_URL: "x" });
    expect(r.errors).toEqual([]);
    expect(r.warnings).toHaveLength(1);
    expect(r.warnings[0]).toMatch(/ignored/);
    expect(r.warnings[0]).not.toMatch(/\bp\b.*\bu\b/); // never echoes the values
  });

  it("never echoes a demo password value in any message", () => {
    const r = checkProductionEnv({ VITE_API_BASE_URL: API, VITE_DEMO_PASSWORD: "hunter2-SECRET" });
    expect(JSON.stringify(r)).not.toContain("hunter2-SECRET");
  });
});
