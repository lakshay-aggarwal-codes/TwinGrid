# Task 3 — Frontend dependency security

## What changed
- `npm audit fix` (no `--force`): `source-map-js` 1.2.1 → 1.2.2 (high, event-loop DoS) fixed.
- `vitest` `^3.2.4` → `^5.0.4` (the only fix for the 2 critical advisories: `tinypool` prototype-pollution RCE and `@vitest/mocker` path traversal). Dev-only. Node 22.20 meets its engine range. It is a major bump, allowed because every previously passing test still passes and the build succeeds.
- `src/test/setup.ts`, line 1: `@testing-library/jest-dom` → `@testing-library/jest-dom/vitest`. Required by the bump: with vitest 5 the bare import stopped typing the matchers (325 `toBeInTheDocument`-style type errors).
- `docs/frontend/waivers/npm_audit.md` for the 5 high + 5 moderate findings that have no safe upgrade.

## Audit (real output lines)
- Before: `14 vulnerabilities (6 moderate, 6 high, 2 critical)`
- After `audit fix`: `{'moderate': 6, 'high': 5, 'critical': 2, 'total': 13}`
- After vitest 5: `10 vulnerabilities (5 moderate, 5 high)`. Remaining highs are all one chain: `braces` (no patched release exists) → `micromatch`, `fast-glob`, `chokidar`, `tailwindcss`. Build-time only, not in the bundle. Waived.

## Version changes (lockfile, 31 entries)
`vitest` 3.2.7→5.0.4, `@vitest/mocker` 3.2.7→5.0.4, `@vitest/spy` 3.2.7→5.0.4, `chai` 5.3.3→6.3.0, `es-module-lexer` 1.7.0→2.3.2, `magic-string` 0.30.21→1.4.3, `std-env` 3.10.0→4.3.0, `tinybench` 2.9.0→6.2.2, `tinyexec` 0.3.2→1.3.1, `why-is-node-running` 2.3.0→3.2.1, `source-map-js` 1.2.1→1.2.2, `obug` added 3.0.0. Removed (folded into vitest 5): `@vitest/expect|pretty-format|runner|snapshot|utils`, `cac`, `check-error`, `deep-eql`, `loupe`, `pathe`, `pathval`, `siginfo`, `stackback`, `strip-literal` (+ its `js-tokens`), `tinypool`, `tinyrainbow`, `tinyspy`, `vite-node`. `package.json` changes only the `vitest` range.

## Test results
- `npm run typecheck`: 0 errors. `npm run lint:ci`: 0 warnings. `vite build`: built.
- `vitest run`: `Test Files 1 failed | 94 passed (95)`, `Tests 3 failed | 1120 passed | 10 skipped` — identical to before the bump. The 3 failures are `Runs.test.tsx` against my sandbox stubs (see Task 2).

## Not verified
- `npm audit --audit-level=high` still exits non-zero because of the waived chain; the waiver needs the owner's signature.
- Run on Node 22.20 in a sandbox, not your CI.
