# Task 2 — Frontend green

## Root causes and fixes (12 files)
| Failure | Cause | Fix |
|---|---|---|
| `bundleScan` (real leak) | `evaluation/flag.ts`, `telemetry/history/flag.ts`, `scenarios/flag.ts` used `env = import.meta.env` as a default argument, so the bundler inlined EVERY `VITE_*` variable, including `VITE_DEMO_USERNAME/PASSWORD`, into the production bundle | Each reads only its own key |
| `OperationsConsole` (5 tests) | The anomaly block still showed the old "Gauge n / 100 … No active alert" text, contradicting the FE-07 contract in `telemetry/anomalyView.ts` | Renders `toAnomalyView(...)`: fail-closed labels, `alert`/`status` roles, score beside backend threshold, provenance |
| `ScenarioPicker` typecheck | `!kind.supported` does not narrow the union with `strict: false` | `kind.supported === false` |
| `alerts`/`esgReport`/`facility` tests did not load | A class declared inside a `vi.mock` factory breaks module loading here | Class moved into `vi.hoisted` |
| `alerts` test | `new Response("{}", {status: 204})` is invalid in Node | 204/205 get a null body |
| `esgReport` test | jsdom `Blob` has no `text()`; Node `Response` stringifies a jsdom Blob | Test returns a jsdom Blob and reads it with `FileReader` |
| `useWhatIf` (4 tests) | `beforeEach(() => mock.mockReset())` returns the mock, which vitest runs as teardown (hung or rejected) | Braces; same latent pattern fixed in `SimulationProvider.test.tsx` |
| `useWhatIf` retry test | Network errors retry with 1 s/2 s delays, beyond `waitFor` | Test client uses `retryDelay: 0` |
| `useFeed` (4 tests) | `ui` element built at import, before `store` exists | `ui` is a function |
| `evaluation/schema` (2 tests) | Test expected `policies.0.x`; the documented format is `policies[0].x` | Test updated |

No assertion was weakened; no test skipped.

## Results (real output, sandbox)
- Before: `19 files failed | 74 passed`, `6 failed | 905 passed`; typecheck 7 errors; build failed.
- After: `npm run typecheck` 0 errors; `npm run lint:ci` 0 warnings; `vite build` built.
- `vitest run`: `3 failed | 1120 passed | 10 skipped`. The 3 failures are `src/pages/Runs.test.tsx`.

## Not verified
- The uploaded zip has no `src/runs/` (`schema`, `flag`, `testFixtures`) or `src/components/runs/` (`RunMonitor`, `RunStart`), though `apiClient.ts` and `Runs.tsx` import them. I used throwaway stubs, NOT in this zip, to load the rest. Apply this zip to your full repo, where those files exist; if `Runs.test.tsx` still fails there, that is separate.
- Backend suites unchanged by this task (26 failures from FastAPI lazy-router route walking, noted in Task 1).
- No browser or CI run.
