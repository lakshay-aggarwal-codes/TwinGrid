# Judges pack

Everything here is backed by a row in [`CLAIMS.md`](CLAIMS.md). TwinGrid is a **simulation-based** platform: say that first.
Run the checks in [`DEMO_CHECKLIST.md`](DEMO_CHECKLIST.md) before going on stage. Step lengths below are targets, not timed.

## Five-minute demo

Sign in as `demo_operator` (the demo script prints the passwords once). Keep "simulated" in your first sentence. [C-01]

| Time | Page | What to do | Say | Claim |
|---|---|---|---|---|
| 0:00 | `/` Live twin | Point at the status bar: connection, last update, origin "Simulated". | "Every number here comes from our own simulator; the bar says so." | [C-05] [C-16] |
| 0:40 | `/` Live twin | Hover and click a rack in the 3D facility. | "A simulated facility layout you can inspect." | [C-10] |
| 1:20 | `/whatif-lab` | Raise ambient temperature, then open the sensitivity chart. | "Two simulated runs side by side; carbon here is a flat assumption, and the page says that." | [C-12] [C-04] |
| 2:10 | `/alerts` | Open an alert, assign it, add a note. | "A small incident workflow with an audit trail." | [C-14] |
| 2:50 | Command palette (Ctrl or Cmd + K) | Type "passport", open the Model Passport. | "Each model shows its status and its limits, including the ones that did badly." | [C-09] [C-16] |
| 3:30 | `/optimizer` | Show the baseline recommendation. Sign in as `demo_admin` in another window to approve a proposal. | "Approval is a recorded decision. Nothing controls equipment." | [C-15] [C-02] |
| 4:15 | `/fleet` | Switch between two sites. | "Five simulated sites from the same simulator; ranks, not real facilities." | [C-17] |
| 4:40 | Close | Show `docs/CLAIMS.md`. | "Every claim has evidence and a boundary." | [C-01] |

Backup if the stack fails: the guided Story Mode (command palette, "Start Story Mode") walks the same pages. [C-16]

## The ten hardest questions

1. **Is this a real facility?** No. It is a simulator; no real measurements are used. [C-01] It is not connected to equipment. [C-02]
2. **Is the physics fitted to a real facility?** No. The values are engineering values, not fitted to any facility. [C-03]
3. **Where does the carbon figure come from?** A flat assumed 475 gCO2/kWh; no carbon file ships. Differences between sites reflect energy use only. [C-04]
4. **What does the forecaster result show?** A 0.523 °C error, 30 minutes ahead, on simulator data. There is no baseline, one run, and no evaluation record, so we do not claim it is accurate. [C-06]
5. **Is the anomaly detector good?** Its F1 of 0.96 used a threshold tuned on the same rows, so it is optimistic. The stricter event-level evaluation has not been run. [C-07]
6. **Does the AI optimizer save energy?** We do not claim it. The five candidates were scored once under the physics-1 protocol and the registered outcome is C: a fixed setting scored higher than every PPO seed, so the recommendation is the simpler controller. The earlier legacy policy was worse than the rule baseline and is quarantined. [C-08]
7. **Is it ready for production use?** No. It has not been deployed to a real platform, the service targets are unmeasured hypotheses, and the test suite has not been seen green on this exact tree. [C-25] [C-32] [C-27]
8. **How secure is it?** Sign-in, roles, security headers, single-use WebSocket tickets and lockout are in place and unit-tested; there has been no independent audit. [C-21] [C-22]
9. **What happens when the live feed drops?** The status bar says so and the client reconnects with jitter and back-fills the gap; this is unit-tested, not load-tested. [C-19] [C-16]
10. **What would it take to connect a real facility?** Integration with the building systems, real data to calibrate the physics and retrain the models, a shadow-mode period comparing recommendations with the current controller, and security and operational review. None of this is built. [C-33]

## What sets it apart (and what that does not mean)

| Differentiator | What is true | Does not mean | Claim |
|---|---|---|---|
| Honest labelling | Origin badges, a status bar and a Model Passport state what is simulated and what is not evaluated. | The models are good. | [C-05] [C-09] |
| Explorable | What-if lab with sensitivity, replay, 3D inspection. | The results transfer to a real site. | [C-10] [C-11] [C-12] |
| Operational workflow | Alert incidents and an admin-approved proposal flow with audit trail. | Anything is applied to equipment. | [C-14] [C-15] |
| Fleet comparison | Five simulated sites ranked on one page. | A multi-site product exists. | [C-17] |
| Engineering discipline | Plugins, migrations, runbooks, generated API reference, a claims ledger. | It has run in production. | [C-24] [C-28] [C-29] |

Related: [`LIMITATIONS.md`](model_cards/LIMITATIONS.md) · [`DATA_TRUTH.md`](model_cards/DATA_TRUTH.md) · [`SLO.md`](SLO.md).


## Engineering talking points (for an interview, not a claims list)

- **Why status is polled rather than pushed over the WebSocket.** The WebSocket carries the high-rate simulated frames; status
  (health, model state, access decisions) is low-rate, must be correct after a reconnect, and is easier to make honest as a
  request that can say "unavailable" than as a message that may simply never arrive.
- **Why the assistant cannot write numbers.** Answers are templates filled from evidence the server fetched, each value carries a
  reference, and anything the evidence does not hold is listed as unknown. There is no language model in the tree to make one up.
- **Why PPO is reported negative.** Its result was registered before it was scored, and the registered outcome is C: a fixed
  setting scored higher than every PPO seed. Reporting that is what the protocol is for. See the optimizer question above.
- **What real facility data would change.** Parameters would be fitted and checked against held-out measurements, carbon would come
  from a licensed time series, and the models would be re-scored on that data first. The design is described in
  `docs/tasks/Task23_calibration_REPORT.md`.
- **Trade-offs worth naming.** One process with a simulator-first design is simple to run and to reason about, and not
  horizontally scaled; the checks and runs that would show otherwise are listed as not run in `docs/roadmap/EVIDENCE_MATRIX.md`.

## Engineering talking points (design choices, not results)

- **Simulation first.** One simulator is the single source of every number, and each surface says so. The trade-off is that nothing here says how a real facility behaves. [C-01]
- **Evidence the assistant cannot change.** The assistant is templates over evidence the server fetched; it has no language model and cannot write a number, so a wrong answer can only come from a wrong source row, which is shown beside it. [C-05]
- **Why the status is polled, not pushed.** The WebSocket carries telemetry; model and run status are fetched on request so a dropped socket can never leave a stale "all good" on screen. [C-19]
- **Why PPO is reported as it is.** The registered rule was written before the scores existed, a fixed setting beat every PPO seed, and the result is shown as registered. [C-08]
- **Carbon.** A flat assumed figure, labelled assumed everywhere; a series counts as real only when dated and documented. [C-04]
- **With real facility data.** The next step would be calibration, designed in [`docs/PHYSICS_V2.md`](PHYSICS_V2.md) and `docs/tasks/Task23_calibration_REPORT.md` if present; none of it is done. [C-03]
