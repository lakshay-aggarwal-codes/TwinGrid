# Task 21 — Design polish, responsive, accessibility in code

**Claim:** a11y fixes applied. Not "WCAG compliant".

## What changed
- **Tokens** (`src/index.css`, `tailwind.config.ts`): page gutter, elevation 1–3, pill radius, type scale (`text-caption/meta/body/title/display`, new names only), card gradient/glow alpha as variables. Dark values are unchanged. Spacing stays on Tailwind's 4px scale. The new tokens are applied in the components touched here; this is not a repo-wide restyle.
- **Dark/light parity**: `:root[data-theme="light"]` defines every colour token. `features/design-polish` adds a header toggle (`aria-pressed`, saved in `localStorage`; dark stays the default). The `dark` class is deliberately not set (it would activate the shadcn `dark:` variants and change the dark look).
- **Colour-blind-safe charts**: `chartPalette.ts` (Okabe-Ito). `SimulationTab` uses it for modes and lines, theme-token chart chrome (grid, axes, tooltip) and outlines on filled marks. Line colours keep ≥3:1 on both the dark and light card (tested). Dash and fill patterns and text remain the non-colour cues.
- **Responsive to 360px**: bottom nav on phones (`MobileBottomNav`, `<sm` only, signed-in only, reserves page space via `.app-shell`); Analytics sidebar is a slim rail on phones and an overlay when open (backdrop + Escape); Live Twin side panels become overlays under 640px; headers use the gutter and wrap; the horizontal header nav is hidden on phones; account menu clears the bottom nav; `100dvh` shell.
- **Transitions / motion**: existing `RotateTransition` already wraps every route (it only gained the `app-shell` class). Global `prefers-reduced-motion` CSS rule added (the GSAP paths already used `motionDuration`). The anomaly flash becomes a static border.
- **Code-level a11y**: names on the sidebar toggle (+`aria-expanded`/`aria-controls`), sidebar sliders (`Slider` now forwards `aria-label` to the thumb), cooling-mode select and collapsed glyphs; heading order fixed on the Analytics tabs (sr-only `h2`), passport drawer (`h4`→`h3`) and "Models in this twin" (`h3`→`h2`). Already present and left as is: live regions for stale/offline (`StatusBar`, freshness chips), Radix dialogs/sheets (focus trap and restore), the keyboard path for the 3D view (arrows/Home/End/Enter/Escape).
- Tests: `registry.test.ts` list gained `design-polish` (the test asks for this). No test removed or weakened.

## Assumptions
- Dark stays default; light is opt-in (no OS auto-switch) so the existing look does not change.
- "Bottom nav" lists Live Twin, Analytics and every role-visible feature page; it scrolls sideways if they do not fit.

## Test results
NOT RUN. `npm ci` cannot complete in this sandbox (no network; npm exits with "Exit handler never called!" and creates no `node_modules/.bin`), so `typecheck`, `lint:ci`, `vitest` and `build` could not be executed. Only a TypeScript syntax parse of every changed file was run: `syntax errors: 0`. New tests (written, not executed): `design-polish/theme.test.ts`, `chartPalette.test.ts`, `polish.test.tsx` (role queries for the theme toggle, bottom nav, sidebar toggle, slider and select names, phone overlay).

## Not verified
- Everything above under Test results; first `npm run verify` may show type or lint nits in the new files.
- Visual result in a browser: light theme (the 3D scene colours in `three/*`, `AnomalyGauge` and the tour overlay still use fixed colours and were not made theme-aware), and layout at 360px.
