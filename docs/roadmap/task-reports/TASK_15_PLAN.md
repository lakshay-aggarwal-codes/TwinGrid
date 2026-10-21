# Task 15 plan (AI-B)

Owned: `src/features/assistant/*`, `src/contract/fixtures-copilot/*`, entry-button edits in `AlertDetail.tsx`, `PassportDrawer.tsx`, `OperationsConsole.tsx` (+ the three "no LLM" comments in `OperationsConsole.tsx`, `LiveTwin.tsx`, `reports/reports.ts`).
Also touched: `features/registry.test.ts` (the feature-id list must now include `assistant`).

1. Synthetic fixtures from section 8.4 (rule_based, stale, unknown_cause, refusal, llm_fallback, hostile_text, rate_limited, offline).
2. `schema.ts` (zod, strict enums) and `api.ts` (same discipline as the alerts client).
3. `model.ts`: request bounds, `[E#]` segmentation, link validation against known routes, labels, error copy.
4. `AssistantDrawer` (Radix sheet: focus trap, Esc), `AnswerView`, `EvidenceTable`, `ExplainButton`, `AssistantHost` (header slot), `store.ts`.
5. Entry points: alert detail, Model Passport, Operations Console status.
6. Tests: model, api, drawer (all fixtures, sanitisation, chips, errors, history, keyboard, alert flow).
7. Gates: `npm run typecheck && npm run lint:ci && npm run test && npm run build` (not runnable in the sandbox).
