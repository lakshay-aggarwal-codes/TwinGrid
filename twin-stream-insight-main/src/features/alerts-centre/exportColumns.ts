import { utcIso, type ExportColumn } from "../reports-export/exportTable";
import type { InboxAlert } from "./model";

/** Task 22: the alerts export. Every time column is UTC ISO-8601; `origin` is the backend's label, empty when it sent none. */
export const ALERT_EXPORT_COLUMNS: readonly ExportColumn<InboxAlert>[] = [
  { key: "id", header: "id", value: (a) => a.id },
  { key: "created_at_utc", header: "created_at_utc", value: (a) => utcIso(a.created_at) },
  { key: "severity", header: "severity", value: (a) => a.severity },
  { key: "status", header: "status", value: (a) => a.status },
  { key: "type", header: "type", value: (a) => a.type },
  { key: "message", header: "message", value: (a) => a.message },
  { key: "score", header: "score", value: (a) => a.score },
  { key: "assignee", header: "assignee", value: (a) => a.assignee },
  { key: "acknowledged_by", header: "acknowledged_by", value: (a) => a.acknowledged_by },
  { key: "acknowledged_at_utc", header: "acknowledged_at_utc", value: (a) => utcIso(a.acknowledged_at) },
  { key: "resolved_by", header: "resolved_by", value: (a) => a.resolved_by },
  { key: "resolved_at_utc", header: "resolved_at_utc", value: (a) => utcIso(a.resolved_at) },
  { key: "origin", header: "origin", value: (a) => a.origin ?? "" },
  { key: "model_version", header: "model_version", value: (a) => a.model_version ?? "" },
];
