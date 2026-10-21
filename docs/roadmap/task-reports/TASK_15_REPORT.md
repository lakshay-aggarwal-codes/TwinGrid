# Task 15 — AI-B Copilot UI and "Explain this"          Status: PARTIAL
Base: uploaded `TwinGrid-main.zip` (owner's `git status` not seen; Tasks 1 to 14 not assumed applied)     Date: 2026-10-20     Environment: no node_modules, no network: `tsc`, `eslint`, `vitest`, `vite build` could not run.

## Summary
The assistant drawer, evidence table, citation chips, mode label, warnings and unknowns blocks, error / retry / rate-limit / offline states and three entry points are written against synthetic section 8.4 fixtures. **None of it has been type-checked, linted or run in vitest or a browser.** The pure logic (request building, citation splitting, link validation, formatting) was run ad hoc in node and passed.

## Acceptance checklist
| Criterion | Status |
|---|---|
| Four frontend gates | NOT RUN |
| Alert opens an evidence-backed explanation without leaving the page | written, unrun: `AlertDetail` "Explain this" -> global drawer, first question asked on open; test `Explain this: alert to explanation` |
| Evidence values inspectable | written, unrun: table of ref, source, entity, field, value+unit, observed_at, origin, freshness; `[E#]` chips are buttons that focus the row |
| Mode shown honestly | written, unrun: "Rule-based explanation" / "Model-phrased (evidence-checked)", plus "no language model is configured" |
| Safe rendering | by construction: no `dangerouslySetInnerHTML`, text nodes only; links only from `links[]`, relative, exact known route (or one id under `/runs`, `/evaluation`); test with `<img onerror>`, `<script>`, `https://`, `//`, `javascript:` |
| Stale / unavailable styled distinctly from errors | written, unrun: dashed note with clock icon vs solid destructive border for errors |
| Retry, rate-limit, offline | written, unrun |
| Focus trap, Esc, live region, mobile | Radix sheet (trap, Esc, focus return), polite live region, `w-full` on small screens; keyboard behaviour not exercised in a browser |
| "No LLM" strings stay true | done in the 3 files |

## Changed files
New: `src/features/assistant/{schema,model,store,api,ExplainButton,EvidenceTable,AnswerView,AssistantDrawer,AssistantHost,index,testFixtures}.ts(x)`, tests `model.test.ts`, `api.test.ts`, `AssistantDrawer.test.tsx`; `src/contract/fixtures-copilot/*.json` + `README.md`; plan and this report.
Edited (minimal): `alerts-centre/AlertDetail.tsx` (button), `explainability/PassportDrawer.tsx` (button), `components/shell/OperationsConsole.tsx` (button + comment/string), `pages/LiveTwin.tsx` and `reports/reports.ts` (comment), `features/registry.test.ts` (feature id list gains `assistant`).

## Commands run
TypeScript `transpileModule` on all 20 changed/new files: 0 syntax diagnostics (not a typecheck). Ad-hoc node run of `model.ts` logic: passed. `npm ci` was not attempted again (no network).

## Pre-existing failures observed
None (nothing ran).

## Not run / blocked
```powershell
cd twin-stream-insight-main
npm ci
npm run typecheck; npm run lint:ci; npm run test; npm run build
```
Then open the app, press Ask in the header, and open an alert's "Explain this".

## Decisions and defaults used
- **Fixtures are synthetic**, hand-written from section 8.4 (README says so); no backend capture exists.
- **Auto-ask on open** for alert / signal / model contexts (first suggested question). A general drawer waits for you.
- **Links:** `/alerts/42` from the section 8.4 example would be shown as plain text, because the app has no such route (alerts live at `/alerts`). Task 14 should send paths that exist (`/alerts`, `/replay`, ...) or Task 15's validator should be extended when an alert deep link exists.
- **Signal entry point:** no signal badge exists yet (Task 16). The button is on the Operations Console status block with `{kind:"signal", id:"pue"}`; **`pue` is my choice of id and Task 14's `get_signal_status` must know it** (else the drawer shows "Not found"). The same `ExplainButton` is ready for Task 16's badge.
- Error codes are read from the HTTP status, not the body (`{error: ...}` vs the repo's problem+json, see Task 13).
- An unknown warning code is shown as received (text), a known one (`llm_unavailable`, `llm_rejected`) as a sentence.

## Requested cross-task changes
Task 14: `links[].path` must be existing routes; accept `signal` id `pue` or tell me the real ids. Task 16: use `ExplainButton` on the signal badge.

## New limitations or risks
- Unrun: type errors, lint findings (`react-hooks/exhaustive-deps` is suppressed once in `AssistantDrawer.tsx` with a reason; that adds 1 suppression to the baseline 16), or test failures are possible. Radix dialog and jsdom behaviour (Escape, `role="dialog"`) is assumed from the existing passport tests.
- `AssistantHost` imports the feature registry (as `TourHost` does) for the known routes: a module cycle that the existing code already tolerates.
- History is lost when the drawer reopens (a new opening is a new conversation, by design).
- Question text is sent to the server; it is never logged client-side.

## Next tasks unblocked
Task 16 (badge entry), Task 24 (journey J5) once Task 14 is live.
