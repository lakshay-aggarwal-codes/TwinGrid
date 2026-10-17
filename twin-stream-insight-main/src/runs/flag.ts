/** FE-16 rollback: the run workflow is on unless `VITE_RUN_WORKFLOW=off` is set at build time. */
export function isRunWorkflowEnabled(env: { VITE_RUN_WORKFLOW?: string } = import.meta.env as { VITE_RUN_WORKFLOW?: string }): boolean {
  return (env.VITE_RUN_WORKFLOW ?? '').trim().toLowerCase() !== 'off';
}
