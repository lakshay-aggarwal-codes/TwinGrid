# Model card: TwinGrid Copilot (assistant)

Status: an evidence-grounded assistant for a **simulator**. It is not a general chatbot and not an autonomous agent.
Evaluation numbers are from `docs/copilot/EVAL_REPORT.md` (offline, fake providers, written by the system's author).

## Intended use

Explain what the dashboard shows, why an alert is red, what a model is and what it cannot do, and where the project's own
documentation says something. Read-only: it has no tool that writes, acknowledges, restarts or configures anything
(`docs/copilot/LIMITS.md`). Out of scope: advice on a real facility, root-cause diagnosis, questions about anything outside
the TwinGrid documents and the simulator's evidence.

## How an answer is made

1. A rule-based builder fills a template with evidence that read-only tools fetched. Numbers appear only as `[E#]` references.
2. Documentation questions (a cue such as "runbook" or "documentation") search a local index of an allow-listed set of
   documents and cite file and heading. No match above the floors gives "not documented", not a guess.
3. Optionally, a language model may rephrase the draft. It never types a number: figures come back as `{{E#}}` placeholders
   replaced from evidence. A reply that adds a number, link, HTML or an unsupported word is thrown away and the rule-based
   text is shown with a warning code.
4. Providers are tried in order (`COPILOT_LLM_PROVIDERS`), each a different provider, within a time budget. If all fail,
   the rule-based answer is returned. A provider failure is never an error for the client.

## Data flow

| Destination | What it receives | What it never receives |
|---|---|---|
| Rule-based path | the question; evidence read from the server's own services | nothing leaves the process |
| Local model (Ollama, flagged local) | question, evidence, draft | nothing leaves the machine |
| Cloud provider (only if configured) | scrubbed question, evidence items with numeric values withheld, retrieved doc passages; documentation questions only unless `COPILOT_LLM_CLOUD_INTENTS` says more | raw telemetry, alert text and ids, user identifiers, keys |

`COPILOT_LLM_LOCAL_ONLY=true` removes every non-local provider. Logs hold provider name, outcome word and request id; never a
prompt, answer or question. Evidence: `docs/security/COPILOT_THREATS.md`, `tests/test_copilot_hardening.py`,
`tests/test_copilot_policy.py`. "Local" is the operator's flag on a provider, not something the code can verify.

## Evaluation (offline, 50 questions, the author wrote them)

| Measure | Result | Target | |
|---|---|---|---|
| Retrieval hit@3, in-corpus (retriever alone) | 0.875 (leave-one-out 0.833) | 0.85 | pass in-sample, below target out-of-sample |
| Correct refusal, out-of-corpus, end to end | **0.800** (retrieval alone 0.900; leave-one-out 0.700) | 0.90 | **fail** |
| Accepted answers containing an unknown number | 0 | 0 | pass |
| Adversarial cases handled | 9 of 9 | all | pass |
| In-corpus questions that reach documentation retrieval | 10 of 24 (0.417) | none set | the main gap |
| Scripted unfaithful model replies rejected | 80 of 80 | n/a | scripted, not real model output |
| Failover under injected faults | 29 of 29 as intended | n/a | fake providers |

One question moves hit@3 by 4.2 points and refusal by 10 points, so these gates are noisy. Real providers were not run.
Re-run after any documentation change: `python scripts/copilot_eval.py --write-report`.

## Limitations

- **Refusal gate fails.** Some out-of-corpus questions get a cited answer from a document that only shares words with them.
- **Most in-corpus questions are not routed to the documents.** Without a docs cue they go to the older keyword intents.
- **Known hole:** a model reply that reverses a passage using only that passage's own words is accepted (10 of 10 scripted
  cases). The guard is lexical, not semantic.
- **Evidence is simulated**; the assistant describes the simulator, not a facility.
- **No conversation memory**, no tools with free text, no autonomy.
- **Docker image has no documents**, so documentation answers are off in the supplied Docker stack.
- Provider limits and the in-process limiter are per process; several workers each count separately.

## Provider terms caveat

Free-tier providers may use prompts to improve their products. Provider data-use terms were not verified
(`docs/copilot/PROVIDERS.md`, table marked "unverified"). Keep sensitive deployments on the local provider.
