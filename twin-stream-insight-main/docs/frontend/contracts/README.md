# Contracts, gates and captures

The frontend never guesses a backend shape. Each payload is checked against a zod schema in `src/contract/`, and the schemas are tested against **real captures** of the running backend. Where the backend did not yet offer something, work was held behind a **gate** until a Contract Confirmation Record (CCR) existed.

## Gate records

Records and raw captures are kept at the repository root, beside the backend: `../../../../docs/frontend/contracts/` from this file.

| Gate | Backend contract | Used by | Record |
|---|---|---|---|
| G-SCN | `GET /api/scenarios`, `GET /api/whatif?scenario_id=…` (BC-09) | FE-15 | [G-SCN.md](../../../../docs/frontend/contracts/G-SCN.md), real-backend run: [G-SCN.real-run.md](../../../../docs/frontend/contracts/G-SCN.real-run.md) |
| G-RUN | `POST /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/result` (BC-10) | FE-16 | [G-RUN.md](../../../../docs/frontend/contracts/G-RUN.md); real-backend run recorded in `G-RUN.real-run.md` (owner record, passed at commit `db92487705ba6ffe554b4c819b8006187966a446`) |
| G-EVAL | `GET /api/evaluations`, `GET /api/evaluations/{id}` (BC-11, backend task BE-G2) | FE-17 | [G-EVAL.md](../../../../docs/frontend/contracts/G-EVAL.md) |
| G-HIST | `GET /api/telemetry/sensors/{external_id}/samples` and `/gaps` (BC-12; the roadmap's `/api/telemetry` paths do not exist) | FE-18 | [G-HIST.md](../../../../docs/frontend/contracts/G-HIST.md) |

Read each record's own **STATUS** line first: it states whether the capture was made on the real backend or in a sandbox, and what is still open. This index does not restate those states; the record is authoritative. Current sign-off state is in [../STATUS.md](../STATUS.md).

Facts that have caused bugs and are worth knowing before touching these screens:

- **Scenario parameter names differ between request and response.** Descriptors and run parameters use `outside_temp` and `chilled_water_temp`; the `/api/whatif` response echoes `inputs.outside_temp_C` and `inputs.chilled_water_temp_C`. Map explicitly.
- **Two different `scenario_set_id`s exist.** The run workflow's is a hash of the *scenario registry* (`sset-<registry_version>-<12 hex>`); the evaluation report's is a hash of the pre-registered *evaluation episodes* (16 hex). They are unrelated and are labelled "Scenario registry set" and "Evaluation scenario set".
- **Runs have exactly five statuses** (`queued`, `running`, `completed`, `failed`, `cancelled`), no progress, no ETA. The UI shows none.
- **History is stored telemetry only.** It must never be filled from the live WebSocket. An empty window is HTTP 200 with `items: []` and is shown as an explicit empty state.
- Ids are opaque. Never parse them.

## Fixtures

`src/contract/fixtures/` holds real captures only: `{ "_meta": { endpoint, method, http_status, captured_at, base_url_host, backend_hash, redactions }, "body": … }`. Never hand-edit them. The only transformation is credential redaction, listed in `_meta.redactions`. Gate-specific raw captures are stored with the gate records above.

## Capture from a running backend

Node ≥ 22 (global `fetch` and `WebSocket`). Use an **operator** account to also capture `POST /api/optimize` (a viewer gets 403 and it is skipped and logged).

```sh
TWINGRID_API_BASE_URL=http://localhost:8000 \
TWINGRID_USERNAME=operator TWINGRID_PASSWORD=… \
[TWINGRID_BACKEND_HASH=<git sha>] [CAPTURE_LIVE_FRAMES=3] [CAPTURE_TIMEOUT_MS=30000] \
node scripts/capture-contract.mjs [--out <dir>]
```

Default output is `src/contract/fixtures` (the committed set); with `--out` the committed set is untouched. It also snapshots the OpenAPI property names of the typed models to `<out>/openapi/typed.json`. Each run appends to `docs/frontend/contracts/capture.log`.

## Detect drift (offline)

```sh
node scripts/capture-contract.mjs --diff <committedDir> <freshDir>
```

Exits 1 when a fixture is missing on either side, an endpoint/method/status changed, or a body **shape** changed (key added/removed, type changed). Values are not compared. `null` matches any type and an empty array matches any array.

CI job `frontend-contract` (`.github/workflows/ci.yml`) re-captures from the compose backend, runs the fixture/schema tests on the fresh captures, diffs against the committed set, and proves the gate can fail on a mutated copy. A schema failure is recorded as a **contract finding**; the schema is never loosened to make it pass. The job and `frontend-e2e` are advisory (`continue-on-error`) until each has one recorded green run; then remove that line.

## Adding a gate record (CCR)

1. State what exists today from code and a real capture, not from the roadmap.
2. Capture on the real backend and record the backend commit and file hashes.
3. Record the vocabulary the backend owns and what it does **not** provide (shown in the UI as "not reported", never inferred).
4. List open decisions and who approved them.
5. Only then start the frontend task.
