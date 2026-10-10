/**
 * FE-17 rollback: the evaluation view is on unless `VITE_EVALUATION_VIEW=off` is set at build time.
 * Turning it off leaves the FE-09 policy-run card as it was; the `/evaluation` route then shows a plain notice.
 */
export function isEvaluationViewEnabled(env: { VITE_EVALUATION_VIEW?: string } = import.meta.env as { VITE_EVALUATION_VIEW?: string }): boolean {
  return (env.VITE_EVALUATION_VIEW ?? '').trim().toLowerCase() !== 'off';
}
