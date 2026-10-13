import type { FeatureRole } from "./types";

const RANK: Record<FeatureRole, number> = { viewer: 0, operator: 1, admin: 2 };

/**
 * UX gate: may a user with `role` see something that needs `minRole`?
 * No requirement -> everyone. A missing or unrecognised role (anything the client does not know) only sees what has
 * no requirement. NOT authoritative: the backend enforces roles on every request.
 */
export function roleAllows(role: string | null | undefined, minRole?: FeatureRole): boolean {
  if (minRole === undefined) return true;
  if (role === null || role === undefined || !Object.prototype.hasOwnProperty.call(RANK, role)) return false;
  return RANK[role as FeatureRole] >= RANK[minRole];
}
