# Task 15 — Frontend audit: accessibility, responsive layout, error recovery

Scope: `twin-stream-insight-main/` (inside TwinGrid-main.zip). Partial audit: see "NOT done".

## Environments
- Sandbox (Linux, Node 22.22.2): typecheck, lint, vitest, `vite build`. No browser (Chromium download blocked).
- User's machine (Windows, Node 24.18.0 — engines wants >=22.20 <23): `npx playwright test e2e/a11y.spec.ts -g "login screen"` (Playwright 1.63.0). Output supplied by the user.

## Baseline (unmodified zip, sandbox)
- vitest: 10 failed / 1926 passed / 10 skipped (7 files). typecheck: 16 errors. `lint:ci`: 3 warnings (fails with `--max-warnings 0`).
- Playwright (user machine): login light + dark scheme pass; **"rejected credentials" scan fails**: `color-contrast` serious on `#login-error`, `#dc2828` on `#141414` = 3.84:1 (needs 4.5:1).

## Issues found (with fix status)
| # | Sev | Where | Finding | Status |
|---|-----|-------|---------|--------|
| 1 | High (security) | `src/runs/flag.ts` | Default arg was bare `import.meta.env`, so the bundler inlined every `VITE_*` (incl. DEV-only `VITE_DEMO_USERNAME/PASSWORD`) into `assets/Runs-*.js`. Reproduced by a production build with sentinel values. `src/test/bundleScan.test.ts` was failing for this reason. | Fixed |
| 2 | Serious (a11y) | `index.css`, all error text | Error text used `--destructive` (fill colour), 3.84:1 on dark card. New `--destructive-text` token (dark 0 85% 65% ≈ 5.6:1 on card; light 0 72% 42% ≈ 6.5:1 on white); 23 files switched from `text-destructive` to `text-destructive-text` (shadcn primitives under `components/ui/` left alone). | Fixed (axe re-run on the user's machine needed) |
| 3 | Medium | `GoalRings.tsx` | `type="number"` turns unparsable text into `""`, which means "clear the target", so Enter on bad input silently deleted the goal and the "Enter a number." alert never showed. Now `type="text" inputMode="decimal"`; existing validation runs. | Fixed |
| 4 | Medium | `CommandPalette.tsx` | Search text survived when the host closed the palette after running a command, so the next open was pre-filtered (hid other commands). Now cleared whenever `open` becomes false. | Fixed |
| 5 | Low | `CommandPalette` / cmdk default scorer | Any scattered subsequence matched ("analyt" matched "Go to Telemetry history"). New `paletteFilter` (all terms must be substrings; word starts rank higher), passed via `CommandDialog commandProps`. | Fixed |
| 6 | Low | `useInspectorHost.ts` | An unknown `?rack=` id stayed in the URL (and copied links) until a rack was selected. Now removed once the topology resolves. | Fixed |
| 7 | Test-only | `registry.test.ts` (missing `admin-console`), `executive-dashboard/components.test.tsx` (throwing `getAllByRole`, stale-timestamp frame, label query matched the Edit button), `TwinHeader.test.tsx` (feature slot widgets add live regions: Slot mocked, the freshness-region assertion is unchanged), `LabPage.test.tsx` (link is built from `window.location`; expectation now the full parameter string) | Stale/incorrect tests, production behaviour verified correct. No assertion on a safety property was removed. | Fixed |

## Tests
- Added: `paletteFilter.test.ts` (4), `src/test/colorContrast.test.ts` (2; verified it FAILS when `--destructive-text` is set back to the old colour).
- After changes (sandbox): vitest **161 files / 1942 passed / 0 failed / 10 skipped**. typecheck still **16 errors** (unchanged, pre-existing). eslint: 0 errors, same 3 warnings.

## NOT done / not verified
- Playwright/axe was NOT re-run after the contrast fix; only the pre-fix failure is evidenced. Re-run: `npx playwright test e2e/a11y.spec.ts -g "login screen"`.
- Not run: signed-in axe sweep (needs backend + `E2E_VIEWER_*`), `smoke`, `stale-surfaces`, `perf` specs, any keyboard-flow spec.
- Not audited: contrast of other states/colours (success/warning/muted text, charts), focus visibility on every control, 200% text scaling, narrow-screen layout, chart text alternatives, duplicate-submit and stale-result handling on run/what-if forms. No claim is made about them.
- Not fixed: 16 typecheck errors (discriminated unions `{ok:true}|{ok:false}` do not narrow, e.g. `TariffDrawer.tsx:42`; likely non-strict tsconfig, unconfirmed) and 3 `react-refresh/only-export-components` warnings (`PpoPanel`, `ProposalsPanel`, `RecommendationCard`) so `npm run verify` / `lint:ci` still fail.
- Build needs `VITE_API_BASE_URL` (non-localhost); built with a placeholder.
- `npm audit` on the user's machine: 9 vulnerabilities (4 moderate, 5 high) after `npm ci`; not triaged.
- User's Node is 24.18.0; the project requires 22.x (EBADENGINE warning).

## Risks
- `--destructive-text` colours were computed against `--card`/`--background`; tinted `bg-destructive/10` backgrounds were estimated (≈5.2:1 dark), not measured by axe.
- Palette matching is now substring-based: typo-tolerance was removed deliberately.
