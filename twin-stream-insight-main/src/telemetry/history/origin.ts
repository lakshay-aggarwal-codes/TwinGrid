/**
 * FE-18: the one explicit origin alias (G-HIST difference #4).
 *
 * The telemetry store says `replay`; `src/provenance` recognises `replayed`. Without this alias a replayed sample would
 * fall to "Unverified source". It is exact-match only: any other string (including `Replay`, `replayed ` or a new
 * value) is passed through unchanged and therefore stays unknown. `src/provenance/**` is not edited.
 */
export function originForProvenance(raw: string | null | undefined): string | null {
  if (raw === undefined || raw === null) return null;
  return raw === 'replay' ? 'replayed' : raw;
}
