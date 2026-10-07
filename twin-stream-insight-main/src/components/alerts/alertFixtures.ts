/** FE-12 test support. Test-only; never import from app code. */
import type { AlertRecord } from "@/api/apiClient";

export function alertRow(over: Partial<AlertRecord> & { id: number }): AlertRecord {
  return {
    created_at: "2026-10-06T10:00:00Z",
    type: "reconstruction_error",
    message: `detection ${over.id}`,
    severity: "WARNING",
    score: 0.1234,
    alert: true,
    acknowledged: false,
    acknowledged_by: null,
    acknowledged_at: null,
    origin: "simulated",
    model_version: "v3",
    dedupe_key: null,
    ...over,
  };
}
