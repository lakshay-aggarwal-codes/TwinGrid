## What and why

<!-- One or two sentences. Link the issue if there is one. -->

## Checklist

- [ ] `ruff check .` and `pytest tests -m "not postgres"` pass locally (backend changes)
- [ ] `npm run verify` passes in `twin-stream-insight-main` (frontend changes)
- [ ] New or changed behaviour has a test; no test was weakened, skipped or deleted to get green
- [ ] Migrations are additive and there is still exactly one Alembic head (`python audit_alembic_graph.py`)
- [ ] Routes changed: `python scripts/gen_api_reference.py` re-run and `docs/api/` committed
- [ ] Simulated data stays labelled simulated; no "measured", "validated" or "production-ready" claim without evidence
- [ ] No secrets, tokens or credentials in code, logs, URLs or the frontend bundle
- [ ] Physics / reward / observation-space change: noted below that checkpoints may need retraining

## Notes for the reviewer

<!-- Risks, follow-ups, anything NOT verified. -->
