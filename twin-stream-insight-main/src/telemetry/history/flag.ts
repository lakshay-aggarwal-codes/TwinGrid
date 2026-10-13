/**
 * FE-18 rollback: the telemetry-history view is on unless `VITE_TELEMETRY_HISTORY=off` is set at build time.
 * Turning it off leaves the live feed untouched; the `/telemetry` route then shows a plain notice.
 */
// Read the one key, never `import.meta.env` itself: a bare reference makes the bundler inline EVERY VITE_* variable (incl. DEV-only demo credentials) into the production bundle.
export function isTelemetryHistoryEnabled(
  env: { VITE_TELEMETRY_HISTORY?: string } = { VITE_TELEMETRY_HISTORY: import.meta.env.VITE_TELEMETRY_HISTORY as string | undefined },
): boolean {
  return (env.VITE_TELEMETRY_HISTORY ?? '').trim().toLowerCase() !== 'off';
}
