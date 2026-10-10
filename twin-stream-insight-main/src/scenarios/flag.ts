/**
 * FE-15 rollback: the scenario library is on unless `VITE_SCENARIO_LIBRARY=off` is set at build time.
 * Turning it off leaves the existing raw sliders ("Custom parameters (preview)") as the only way to configure a preview.
 */
export function isScenarioLibraryEnabled(env: { VITE_SCENARIO_LIBRARY?: string } = import.meta.env as { VITE_SCENARIO_LIBRARY?: string }): boolean {
  return (env.VITE_SCENARIO_LIBRARY ?? '').trim().toLowerCase() !== 'off';
}
