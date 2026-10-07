/** FE-12: pure alert view-model helpers. Nothing here invents a field, a state or an explanation. */
import { parseInstant } from '@/contract/time';
import { buildProvenance, type ProvenanceView } from '@/provenance';
import type { AlertRecord } from '@/api/apiClient';

export type SeverityIcon = 'info' | 'warning' | 'critical' | 'unknown';

export interface SeverityView {
  /** Backend text, verbatim (unknown values are shown as received). */
  readonly text: string;
  readonly icon: SeverityIcon;
  readonly known: boolean;
}

/** Known severities get an icon shape + text; anything else is a NEUTRAL badge carrying the raw text. */
export function severityView(severity: unknown): SeverityView {
  const raw = typeof severity === 'string' && severity.trim() !== '' ? severity.trim().slice(0, 32) : 'not reported';
  switch (severity) {
    case 'INFO':
      return { text: raw, icon: 'info', known: true };
    case 'WARNING':
      return { text: raw, icon: 'warning', known: true };
    case 'CRITICAL':
      return { text: raw, icon: 'critical', known: true };
    default:
      return { text: raw, icon: 'unknown', known: false };
  }
}

const pad = (n: number) => String(n).padStart(2, '0');

export interface TimeView {
  readonly text: string;
  /** true when the backend sent no offset and UTC was assumed. */
  readonly assumed: boolean;
  readonly reported: boolean;
}

/** Backend alert time via `parseInstant('alert')`, shown in UTC; "(UTC assumed)" when the offset was absent. */
export function alertTime(value: string | null | undefined): TimeView {
  if (value === null || value === undefined || value === '') return { text: 'not reported', assumed: false, reported: false };
  const p = parseInstant(value, 'alert');
  if (!p.ok || p.kind === 'sim') return { text: 'not reported (unreadable)', assumed: false, reported: false };
  const d = new Date(p.epochMs);
  const text = `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`;
  return { text: p.offsetAssumed ? `${text} (UTC assumed)` : text, assumed: p.offsetAssumed, reported: true };
}

/** The detector's reconstruction error, labelled as such. Never a percentage. */
export function scoreLabel(score: number): string {
  return `Detector score (reconstruction error): ${score.toFixed(4)}`;
}

export type LifecycleState = 'new' | 'acknowledged';

/** Exactly what the backend returns today: not acknowledged / acknowledged. Snooze and resolve are not rendered (G-ALERT). */
export function lifecycleOf(a: Pick<AlertRecord, 'acknowledged'>): LifecycleState {
  return a.acknowledged ? 'acknowledged' : 'new';
}

export interface AlertGroup {
  /** `dedupe_key`, or null for a row that has none (those are never merged). */
  readonly key: string | null;
  readonly rows: readonly AlertRecord[];
}

/**
 * Group rows by backend `dedupe_key` for display ("episode"). EVERY row is kept, in its original order; groups appear at the
 * position of their first row. Rows without a key are their own group of one.
 */
export function groupByEpisode(alerts: readonly AlertRecord[]): AlertGroup[] {
  const groups: Array<{ key: string | null; rows: AlertRecord[] }> = [];
  const byKey = new Map<string, { key: string | null; rows: AlertRecord[] }>();
  for (const a of alerts) {
    const key = typeof a.dedupe_key === 'string' && a.dedupe_key !== '' ? a.dedupe_key : null;
    if (key === null) {
      groups.push({ key: null, rows: [a] });
      continue;
    }
    const existing = byKey.get(key);
    if (existing) existing.rows.push(a);
    else {
      const g = { key, rows: [a] };
      byKey.set(key, g);
      groups.push(g);
    }
  }
  return groups;
}

/** FE-05 view for an alert: origin and model version as the backend sent them (absent origin = Unverified source). */
export function alertProvenance(a: AlertRecord): ProvenanceView {
  return buildProvenance({
    source: { kind: 'alert' },
    origin: a.origin,
    modelVersion: a.model_version,
  });
}

/** Optional fields that, when the backend returns them, replace the "no sensor attribution" notice. Returned verbatim. */
const ATTRIBUTION_FIELDS = ['sensor_reading_id', 'trigger', 'context'] as const;

export interface ExtraEvidence {
  readonly field: string;
  readonly value: string;
}

export function attributionEvidence(a: AlertRecord): ExtraEvidence[] {
  const rec = a as unknown as Record<string, unknown>;
  const out: ExtraEvidence[] = [];
  for (const field of ATTRIBUTION_FIELDS) {
    const v = rec[field];
    if (v === undefined || v === null || v === '') continue;
    out.push({ field, value: typeof v === 'object' ? JSON.stringify(v) : String(v) });
  }
  return out;
}
