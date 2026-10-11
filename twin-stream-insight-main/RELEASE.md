# Frontend release checklist

## Every release (automated: `.github/workflows/ci.yml`, job `frontend`)

`npm run verify` runs, in order: `typecheck`, `lint:ci`, `test`, `build`. CI runs the same steps from a clean `npm ci`, then `npm audit --audit-level=high`.

- `lint:ci` = `eslint . --max-warnings 0` (`package.json`). Zero errors and zero warnings are required; the IG-00 run passed with no output.
- `build` refuses to run in production mode if `VITE_API_BASE_URL` is unset, or if the API URL is localhost (`vite.config.ts`). It warns on plain `http://` and on an unset `VITE_ERROR_REPORT_URL`.

## Manual steps before deploy

1. Build with the real environment (`.env.production` or host build vars; see `.env.example`).
2. `npm run preview` and load the site against the real backend: header shows LIVE, all five modes switch, a rack selects/focuses, Incidents lists alerts.
3. Confirm `VITE_ERROR_REPORT_URL` points at a collector someone monitors.

## Things to know

- **`VITE_DEMO_PASSWORD` is public.** Vite inlines it into the bundle. Use a dedicated low-privilege `viewer` account and treat the password as published.
- **Runtime errors reach an operator only if `VITE_ERROR_REPORT_URL` is set.** The frontend POSTs JSON reports (throttled, no tokens) to it; this repo has no receiving endpoint.
- Do not use `npm install --legacy-peer-deps` to work around resolver errors; fix the dependency ranges instead.

## Previously accepted lint warnings (historical: `lint:ci` now allows 0 and passed in the IG-00 run, so none are currently reported)

In vendor shadcn files `components/ui/{badge,button,form,navigation-menu,sidebar,sonner,toggle}.tsx`. They export a variants helper or hook next to a component, which only affects dev-server hot reload. No production impact; not worth diverging from upstream shadcn files.

## Accepted vulnerabilities (historical count 2 moderate; the IG-00 `npm audit` reports 13: 5 moderate, 6 high, 2 critical; only the moderate vitest item below was ever accepted)

| Package | Advisory | Why accepted |
|---|---|---|
| `vitest` / `@vitest/mocker` (3.x) | GHSA-82fw-gwwq-j7x9, path traversal via redirect mocks | Dev/test-only; never in the production bundle and only reachable while running tests. The fix is vitest 5 (major); vitest 4.1.11 failed to install with this dependency tree (npm resolver error), and forcing it needs `--legacy-peer-deps`, which was judged the larger risk. Revisit when upgrading the test toolchain. |

Resolved in Stage 15: 26 -> 2 (vite 5->7, react-router-dom 6->7 and transitive fixes for lodash, rollup, postcss, nanoid, ws, picomatch and others).
