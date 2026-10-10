# Frontend documentation index

TwinGrid is **simulator-only**: nothing here describes or controls a real facility.

| Document | Read it to… |
|---|---|
| [../../README.md](../../README.md) | run, test, configure and navigate the code |
| [STATUS.md](STATUS.md) | see which tasks are done, which evidence exists, and what is **not** signed off |
| [contracts/README.md](contracts/README.md) | understand gates (G-*), contract records, how to capture and diff real backend responses |
| [PROVENANCE_AND_FRESHNESS.md](PROVENANCE_AND_FRESHNESS.md) | understand origin/quality/freshness states and the auth/WebSocket reconnect rules |
| [RISKS.md](RISKS.md) | see accepted risks and known gaps |
| [../../RELEASE.md](../../RELEASE.md) | release and deploy checklist |
| [baseline/BASELINE.md](baseline/BASELINE.md) | FE-00 verification record (historical) |
| [baseline/BACKEND_RECONCILIATION.md](baseline/BACKEND_RECONCILIATION.md) | FE-00 reconciliation record (historical) |
| [a11y/FE-19.md](a11y/FE-19.md) | accessibility checklist and evidence *(delivered with FE-19)* |
| [perf/FE-20.md](perf/FE-20.md) | performance budgets, harness, breach list *(delivered with FE-20)* |

Gate records (`G-SCN`, `G-RUN`, `G-EVAL`, `G-HIST`) and their raw captures live at the **repository root** in `docs/frontend/contracts/`, next to the backend they describe; see [contracts/README.md](contracts/README.md).
