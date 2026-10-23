# Task 19: optimizer UI, baseline recommendation and approvals

No new environment variables.

| Setting | Used for | Default |
|---|---|---|
| `RATE_LIMIT_WHATIF` | `GET /api/optimizer/baseline-recommendation`, `GET /api/optimizer/sandbox` (one bounded twin computation each) | existing |
| `RATE_LIMIT_OPTIMIZE` | `POST /api/optimizer/proposals`, `POST /api/optimizer/proposals/{id}/decision` | existing |

## Endpoints (plugin `api/plugins/optimizer_proposals.py`)

| Route | Who | Notes |
|---|---|---|
| `GET /api/optimizer/baseline-recommendation` | signed-in | best usable baseline (PID or rule) by its **stored** validation reward, its set-points for the given inputs, and the twin-simulated effect vs the current settings |
| `GET /api/optimizer/sandbox` | signed-in | same prediction for chosen set-points; persists nothing (ADR 007) |
| `POST /api/optimizer/proposals` | operator, admin | server recomputes the prediction; `422 unsafe_prediction` if the simulated outlet exceeds the limit |
| `GET /api/optimizer/proposals?status=&limit=` | signed-in | |
| `POST /api/optimizer/proposals/{id}/decision` | admin only | `approve` or `reject`, once (`409 not_pending`); never the proposer (`403 self_decision`) |

Query inputs: `utilisation`, `outside_temp`, `water_stress`, `current_mode`, `current_chilled_water_temp`, optional `inlet_temp_c`
(a measured value; without it the PID baseline reports its nominal set-point, with it one rate-limited PID step).

## Storage (migration `20261006000000`, additive)

New table `optimizer_proposals` (every row has `origin = simulated`, status `pending|approved|rejected`, the server-computed
`predicted` effect, `decided_by/at`, `decision_note`). Downgrade drops it.

## Audit

`optimizer_proposal_created`, `optimizer_proposal_approved`, `optimizer_proposal_rejected` (atomic, with the change; note text is
not copied). Denied attempts: `permission_denied` (wrong role, or `reason=self_decision`). These actions are not in
`audit_service.EVENT_MODES` (a test pins that table).

## Admin role

The backend issues `viewer`/`operator` at registration; `admin` accounts come from the seed script or the database. Only the string
`admin` may decide. An `admin` can also propose.

## Frontend

Feature `optimizer-approvals`, route `/optimizer` (nav group "Operate"). Approving records a decision; **nothing is applied to equipment**.
