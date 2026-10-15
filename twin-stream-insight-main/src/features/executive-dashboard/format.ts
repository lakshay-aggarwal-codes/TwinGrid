/** Task 16: number and time formatting shared by the executive dashboard. Pure. */

export const MINUS = "\u2212";

/** `1234.5` -> "1,235" (decimals 0). Non-finite -> null so a caller cannot print "NaN". */
export function fmtNumber(value: number, decimals: number): string | null {
  if (!Number.isFinite(value)) return null;
  return value.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

/** Signed percent with a real minus sign: "+4.1%" / "\u22126.0%". */
export function fmtSignedPct(pct: number, decimals = 1): string {
  const abs = Math.abs(pct).toFixed(decimals);
  if (Number(abs) === 0) return `${(0).toFixed(decimals)}%`;
  return `${pct > 0 ? "+" : MINUS}${abs}%`;
}

/** `HH:MM:SS UTC` of an epoch-ms instant. UTC only. */
export function utcClock(ms: number): string {
  return `${new Date(ms).toISOString().slice(11, 19)} UTC`;
}

/** "45 s", "12 min", "1 h 05 min". */
export function fmtSpan(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest === 0 ? `${h} h` : `${h} h ${String(rest).padStart(2, "0")} min`;
}
