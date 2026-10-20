/** Test fixtures only (not imported by the app). Shapes mirror `/api/admin/access-requests` (contract section 8.1). */
import type { AccessRequest, AccessRequests } from "./schema";

export const accessRequest = (over: Partial<AccessRequest> = {}): AccessRequest => ({
  id: "6f1c2b0e-0000-4000-8000-000000000001",
  ref: "K7Q2M9XD4TAB",
  name: "Ada Lovelace",
  email: "ada@example.com",
  purpose: "Reviewing the project",
  status: "pending",
  created_at: "2026-10-20T09:00:00Z",
  expires_at: "2026-10-27T09:00:00Z",
  decided_at: null,
  decided_by: null,
  notify_state: "sent",
  notify_attempts: 1,
  ...over,
});

export const accessPage = (items: AccessRequest[] = [accessRequest()], next: string | null = null): AccessRequests => ({
  items,
  next_before_id: next,
});
