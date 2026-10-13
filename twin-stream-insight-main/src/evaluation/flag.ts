/**
 * FE-17 rollback: the evaluation view is on unless `VITE_EVALUATION_VIEW=off` is set at build time.
 * Turning it off leaves the FE-09 policy-run card as it was; the `/evaluation` route then shows a plain notice.
 */
// Read the one key, never `import.meta.env` itself: a bare reference makes the bundler inline EVERY VITE_* variable (incl. DEV-only demo credentials) into the production bundle.
export function isEvaluationViewEnabled(env: { VITE_EVALUATION_VIEW?: string } = { VITE_EVALUATION_VIEW: import.meta.env.VITE_EVALUATION_VIEW as string | undefined }): boolean {
  return (env.VITE_EVALUATION_VIEW ?? '').trim().toLowerCase() !== 'off';
}
