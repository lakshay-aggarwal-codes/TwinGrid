/**
 * FE-18 rollback: the telemetry-history view is on unless `VITE_TELEMETRY_HISTORY=off` is set at build time.
 * Turning it off leaves the live feed untouched; the `/telemetry` route then shows a plain notice.
 */
export function isTelemetryHistoryEnabled(
  env: { VITE_TELEMETRY_HISTORY?: string } = import.meta.env as { VITE_TELEMETRY_HISTORY?: string },
): boolean {
  return (env.VITE_TELEMETRY_HISTORY ?? '').trim().toLowerCase() !== 'off';
}
