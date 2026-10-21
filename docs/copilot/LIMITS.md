# Copilot limits

What the in-app assistant (`POST /api/copilot/ask`, the "Explain this" drawer) can and cannot do. Written for operators,
reviewers and anyone deciding how far to trust an answer. `tests/test_copilot_adversarial.py` checks the numbers and
statements below against the code, so this file cannot silently drift.

## What it is

A **rule-based** assistant. Each answer is a template filled with *evidence* that read-only tools collected from the
application's own services. Numbers and names reach the answer only as `[E#]` markers that point at an evidence item
(source, entity, field, value, unit, time, origin, freshness). There is no language model in this tree.

An optional model-phrased mode is planned (Task 24). It is switched by `COPILOT_LLM_ENABLED`, is **off by default**, and
is not part of the code this document describes. Until it exists and this file is updated, every response has
`mode: "rule_based"` and `limits.provider_configured: false`.

## What the assistant cannot do

- **It cannot act.** There is no tool that writes, acknowledges, deletes, restarts, configures or calls out. The tool
  list is an allow-list of `get_*` / `find_*` readers; a request such as "acknowledge all alerts" changes nothing and
  is answered with what the assistant can do instead.
- **It cannot determine a root cause.** The cause of an alert is always reported as *not determined by available
  evidence*. It can show the score, the threshold and which input is furthest from its training range, and nothing more.
- **It cannot make a number up.** A value it states is a stored value with a source and a time. A missing, stale,
  future-dated or valueless reading is listed under *not known*; it is never reported as normal or live.
- **It cannot show more than the signed-in user can already read.** Viewer, operator and admin accounts receive the same
  evidence. It has no access to user accounts, password hashes, the audit log or access requests, and a question that
  asks for them, or claims a higher role, receives the same answer as any other question.
- **It cannot be instructed by data.** The question, the chat history and the text stored in an alert are used only to
  pick a topic by keyword; stored alert text is shown once, as quoted data, with bracket characters removed. It adds no
  evidence, no link and no claim.
- **It cannot vouch for the models.** All model figures describe the **simulated** facility the twin runs on
  (`data_origin: synthetic`). They are not calibrated against, or validated on, a real facility, and the assistant does
  not say otherwise. The claims ledger (`docs/CLAIMS.md`) is the reference for what is and is not claimed.
- **It cannot compare with the past.** "What changed since yesterday?" is answered with a statement that stored-history
  comparison is not available in this version.
- **It cannot name a real facility.** The data shown is simulated or replayed; the assistant has no knowledge of any
  real site.

## Bounds

| Item | Limit |
|---|---|
| Question | 500 characters |
| History entries accepted | 6 (accepted for the contract; they never change an answer) |
| Answer | 1500 characters |
| Request body | the application-wide body limit (413 above it) |
| Rate | the existing `state` request class (30 per minute) |
| Evidence items per answer | 24 |

Malformed or oversized input is refused with a 4xx problem response. It is never a server error.

## Who can ask

Any signed-in user: viewer, operator, admin. Anonymous requests are refused. **Known issue (cross-task):** the public
demo session is currently refused (`403 demo_read_only`) because `POST /api/copilot/ask` is not in
`ALLOWED_DEMO_WRITES` in `api/demo_guard.py`. The route only reads, so adding it there is safe; until then the demo
visitor cannot use the assistant. `tests/test_copilot_adversarial.py` tracks this with a strict expected-failure.

## What is logged

One line per answered request: the request id, the mode, the intent and the number of evidence items. The question,
the history, stored alert text, telemetry values and the answer are **not logged** at any level, and neither is the
`Authorization` header.

## If the optional model mode is enabled later

The rules above are properties of the *response*, not of the generator: every invariant in the test suite
(`assert_grounded`, `assert_no_claims`) must hold for model-phrased text too, and a model answer that fails them is
replaced by the rule-based answer with a `llm_rejected` warning. A provider that is unreachable degrades the same way
(`llm_unavailable`). That behaviour is **not yet verified**: it needs Task 24.
