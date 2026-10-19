/** FE-16 rollback: the run workflow is on unless `VITE_RUN_WORKFLOW=off` is set at build time. */
// Read the one key, never `import.meta.env` itself: a bare reference makes the bundler inline EVERY VITE_* variable (incl. DEV-only demo credentials) into the production bundle.
export function isRunWorkflowEnabled(
  env: { VITE_RUN_WORKFLOW?: string } = { VITE_RUN_WORKFLOW: import.meta.env.VITE_RUN_WORKFLOW as string | undefined },
): boolean {
  return (env.VITE_RUN_WORKFLOW ?? '').trim().toLowerCase() !== 'off';
}
