# npm audit waiver (Task 3)

Scope: `twin-stream-insight-main`. Audited 2026-10-13 with `npm audit --audit-level=high`.
Result after Task 3: **0 critical, 5 high, 5 moderate**. All remaining findings come from one unpatched advisory chain and from two moderate dev-tool packages, waived below.

| Advisory | Package(s) | Dev/prod | Why it is waived | Expiry | Sign-off |
|---|---|---|---|---|---|
| GHSA-vfj7-8cjw-p6xm (braces: stack exhaustion on deeply nested patterns, CVSS 7.5) | `braces` (3.0.3), and through it `micromatch`, `fast-glob`, `chokidar`, `tailwindcss` (3.4.19) | Listed under `dependencies` but **build-time only** (Tailwind CLI file globbing). Not in the browser bundle (`grep braces dist/assets/*.js` finds nothing). | No patched `braces` exists (3.0.3 is the latest release and is affected). The only escape is Tailwind 4, a styling-pipeline rewrite that is not a security patch. Exploiting it needs an attacker-controlled glob pattern fed to the build; Tailwind's patterns are fixed in `tailwind.config`. | 2027-01-13 | OWNER MUST SIGN |
| GHSA-rj75-hqrm-r3gf (postcss-selector-parser: quadratic selector parsing) | `postcss-selector-parser`, `postcss-nested`, `tailwindcss-animate` | Build-time only | Fix needs `postcss-selector-parser` 7, which Tailwind 3 does not accept. Moderate; parses our own CSS at build time. | 2027-01-13 | OWNER MUST SIGN |
| Same Tailwind chain | `@tailwindcss/typography`, `lovable-tagger` | Dev-only | The "fix" npm offers is a downgrade/major swap (`lovable-tagger@1.0.20`, `typography@0.5.4`) with no security gain. Moderate. | 2027-01-13 | OWNER MUST SIGN |
| GHSA-mrhx-c7xc-m3w5 (zod: memory exhaustion validating oversized arrays with many failing elements, CVSS 4.0 8.2, unreviewed) | `zod` (3.25.76) | Production dependency (response validation in `src/contract/schemas`) | The advisory lists no patched release, so there is nothing to upgrade to. Zod here parses responses from our own backend, not arbitrary user uploads, so an attacker needs control of the backend response. Re-check when a patched zod ships. Gate: `scripts/npm-audit-gate.mjs` (the id and expiry are listed there too and must match this row). | 2027-01-13 | OWNER MUST SIGN |

Re-check when `braces` publishes a patched release or the project moves to Tailwind 4.
