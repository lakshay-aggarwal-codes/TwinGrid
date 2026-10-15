import type { InboxAlert, Timeline } from "./model";

/** SYNTHETIC alert rows for tests (the shape of `GET /api/alerts/inbox`). */
export function alertRow(over: Partial<InboxAlert> = {}): InboxAlert {
  return {
    id: 1,
    created_at: "2026-10-01T08:00:00+00:00",
    type: "anomaly",
    message: "Inlet temperature anomaly",
    severity: "WARNING",
    score: 0.42,
    origin: "simulated",
    model_version: "sha256-test",
    acknowledged: false,
    acknowledged_by: null,
    acknowledged_at: null,
    status: "open",
    assignee: null,
    resolved_by: null,
    resolved_at: null,
    ...over,
  };
}

export const TIMELINE_1: Timeline = {
  alert_id: 1,
  entries: [
    { at: "2026-10-01T08:00:00+00:00", kind: "created", actor: null, summary: "Alert raised by the detector", note: null },
    { at: "2026-10-01T08:05:00+00:00", kind: "note", actor: "op1", summary: "Note added", note: "Checked CRAC-02" },
  ],
};
