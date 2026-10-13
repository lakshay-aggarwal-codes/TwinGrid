/**
 * FE-15 rollback: the scenario library is on unless `VITE_SCENARIO_LIBRARY=off` is set at build time.
 * Turning it off leaves the existing raw sliders ("Custom parameters (preview)") as the only way to configure a preview.
 */
// Read the one key, never `import.meta.env` itself: a bare reference makes the bundler inline EVERY VITE_* variable (incl. DEV-only demo credentials) into the production bundle.
export function isScenarioLibraryEnabled(env: { VITE_SCENARIO_LIBRARY?: string } = { VITE_SCENARIO_LIBRARY: import.meta.env.VITE_SCENARIO_LIBRARY as string | undefined }): boolean {
  return (env.VITE_SCENARIO_LIBRARY ?? '').trim().toLowerCase() !== 'off';
}
