import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import { componentTagger } from "lovable-tagger";

/** Variables a production bundle cannot work without. Vite inlines VITE_*
 * values at build time, so a missing one is baked in as "undefined" and only
 * fails once a user opens the app. Fail the build instead. */
const REQUIRED_PRODUCTION_ENV = ["VITE_API_BASE_URL", "VITE_DEMO_USERNAME", "VITE_DEMO_PASSWORD"] as const;

/** Pure + exported-by-shape for the checks below; returns human-readable problems. */
function checkProductionEnv(env: Record<string, string>): { errors: string[]; warnings: string[] } {
  const errors: string[] = [];
  const warnings: string[] = [];
  for (const key of REQUIRED_PRODUCTION_ENV) {
    if (!env[key]?.trim()) errors.push(`${key} is not set`);
  }
  const api = env.VITE_API_BASE_URL?.trim();
  if (api) {
    if (/^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/i.test(api)) {
      errors.push(`VITE_API_BASE_URL points at ${api}; a production bundle must not target localhost`);
    } else if (/^http:\/\//i.test(api)) {
      warnings.push(`VITE_API_BASE_URL is plain http:// (${api}); tokens and telemetry would travel unencrypted`);
    }
  }
  const report = env.VITE_ERROR_REPORT_URL?.trim();
  if (!report) {
    warnings.push("VITE_ERROR_REPORT_URL is not set; runtime errors will only appear in browser consoles");
  }
  return { errors, warnings };
}

// https://vitejs.dev/config/
export default defineConfig(({ mode, command }) => {
  if (command === "build" && mode === "production") {
    const env = loadEnv(mode, process.cwd(), "VITE_");
    const { errors, warnings } = checkProductionEnv(env);
    warnings.forEach((w) => console.warn(`\n[env check] warning: ${w}`));
    if (errors.length > 0) {
      throw new Error(
        `Production build blocked by environment check:\n  - ${errors.join("\n  - ")}\n` +
          `Copy .env.example to .env.production (or set these in your host's build environment) and rebuild.`,
      );
    }
  }

  return {
    server: {
      host: "::",
      port: 8080,
      hmr: {
        overlay: false,
      },
    },
    plugins: [react(), mode === "development" && componentTagger()].filter(Boolean),
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
      dedupe: ["react", "react-dom"],
    },
  };
});
