/** FE-16: pure run view-model. No React, no clock, no network. The backend's own status is shown; nothing is invented. */
import { isApiError } from '@/api/apiError';
import type { RunSubmitBody } from '@/api/apiClient';
import type { ProvenanceInput } from '@/provenance';
import type { ScenarioRunRequest } from '@/scenarios/model';
import type { RunRecord, RunResult } from './schema';

// ------------------------------------------------------------------------------------------------ status

/** Exactly the backend set (G-RUN). `unavailable` is not a status. */
export const RUN_STATUSES = ['queued', 'running', 'completed', 'failed', 'cancelled'] as const;
export type RunStatus = (typeof RUN_STATUSES)[number];
export type StatusId = RunStatus | 'unrecognised';

export const UNRECOGNISED_STATUS_TEXT = 'Unrecognised status';

export interface StatusView {
  readonly id: StatusId;
  readonly text: string;
  readonly description: string;
  /** Final: the backend will not change it. */
  readonly terminal: boolean;
  /** Whether the page keeps asking the backend. */
  readonly polling: boolean;
}

export function knownStatus(status: unknown): RunStatus | null {
  return typeof status === 'string' && (RUN_STATUSES as readonly string[]).includes(status) ? (status as RunStatus) : null;
}

function assertNever(x: never): never {
  throw new Error(`unhandled run status: ${String(x)}`);
}

function viewOf(status: RunStatus): StatusView {
  switch (status) {
    case 'queued':
      return { id: status, text: 'Queued', description: 'The backend accepted this run. No worker has started it yet.', terminal: false, polling: true };
    case 'running':
      return { id: status, text: 'Running', description: 'A worker is computing this run.', terminal: false, polling: true };
    case 'completed':
      return { id: status, text: 'Completed', description: 'The run finished. Its result is fetched separately.', terminal: true, polling: false };
    case 'failed':
      return { id: status, text: 'Failed', description: 'The run did not finish.', terminal: true, polling: false };
    case 'cancelled':
      return { id: status, text: 'Cancelled', description: 'The run was stopped before it finished. It has no result.', terminal: true, polling: false };
    default:
      return assertNever(status);
  }
}

export function describeStatus(status: unknown): StatusView {
  const known = knownStatus(status);
  if (known !== null) return viewOf(known);
  return {
    id: 'unrecognised',
    text: UNRECOGNISED_STATUS_TEXT,
    description: 'The backend reported a status this page does not know. Polling has stopped.',
    terminal: false,
    polling: false,
  };
}

/** A short vocabulary-like token of an unknown status may be echoed; anything else is not. */
export function unrecognisedToken(status: unknown): string | null {
  return typeof status === 'string' && /^[A-Za-z0-9_-]{1,32}$/.test(status) ? status : null;
}

// ------------------------------------------------------------------------------------------------ failure copy

export const FAILURE_COPY = {
  invalid_input: 'The backend rejected the inputs of this run.',
  timeout: 'The run took too long and was stopped.',
  worker_lost: 'The worker running this job was lost.',
  internal_error: 'The run failed inside the backend.',
} as const;
export type FailureCode = keyof typeof FAILURE_COPY;

export const FAILURE_NOT_REPORTED_TEXT = 'The run failed. The backend did not report a reason.';
export const FAILURE_UNRECOGNISED_TEXT = 'The run failed. The failure reason was not recognised.';

/** Fixed copy per backend code. The code itself is never shown, and an unknown code is never echoed. */
export function failureText(code: unknown): string {
  if (code === null || code === undefined) return FAILURE_NOT_REPORTED_TEXT;
  return typeof code === 'string' && Object.prototype.hasOwnProperty.call(FAILURE_COPY, code) ? FAILURE_COPY[code as FailureCode] : FAILURE_UNRECOGNISED_TEXT;
}

// ------------------------------------------------------------------------------------------------ backend time only

const pad = (n: number) => String(n).padStart(2, '0');
const HAS_OFFSET = /(Z|[+-]\d{2}:?\d{2})$/i;

/** Milliseconds for an aware ISO-8601 instant; an offset-less or unreadable one is null. */
function instantMs(iso: string | null | undefined): number | null {
  if (typeof iso !== 'string' || !HAS_OFFSET.test(iso)) return null;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : null;
}

/** `2026-10-09 18:53:00 UTC` from a backend timestamp, or null when absent, offset-less or unreadable. */
export function serverTimeText(iso: string | null | undefined): string | null {
  const t = instantMs(iso);
  if (t === null) return null;
  const d = new Date(t);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`;
}

export interface Row {
  readonly id: string;
  readonly label: string;
  readonly value: string;
}

type TimeFields = Pick<RunRecord, 'status' | 'created_at' | 'started_at' | 'ended_at'>;

function timeValue(iso: string | null | undefined, whenEmpty: string): string {
  if (iso === null || iso === undefined) return whenEmpty;
  return serverTimeText(iso) ?? 'unreadable';
}

/** Backend timestamps. An empty one on a non-final run says why; on a final run it says "not reported", never blank. */
export function timeRows(r: TimeFields): Row[] {
  const view = describeStatus(r.status);
  const final = view.terminal;
  return [
    { id: 'created', label: 'Created', value: timeValue(r.created_at, 'not reported') },
    { id: 'started', label: 'Started', value: timeValue(r.started_at, final || view.id === 'running' ? 'not reported' : 'Not started yet') },
    { id: 'ended', label: 'Ended', value: timeValue(r.ended_at, final ? 'not reported' : 'Not ended yet') },
  ];
}

/** Difference of two backend instants in ms; null for an unreadable, offset-less or backwards pair. */
export function durationMs(from: string | null | undefined, to: string | null | undefined): number | null {
  const a = instantMs(from);
  const b = instantMs(to);
  return a === null || b === null || b < a ? null : b - a;
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.floor(ms)} ms`;
  if (ms < 60_000) return `${Number((ms / 1000).toFixed(1))} s`;
  return `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)} s`;
}

/** Elapsed figures are differences between two backend timestamps, never against the browser's now. */
export function durationRows(r: Pick<RunRecord, 'created_at' | 'started_at' | 'ended_at'>): Row[] {
  const rows: Row[] = [];
  const waited = durationMs(r.created_at, r.started_at);
  const ran = durationMs(r.started_at, r.ended_at);
  if (waited !== null) rows.push({ id: 'waited', label: 'Waited in queue', value: formatDuration(waited) });
  if (ran !== null) rows.push({ id: 'ran', label: 'Ran for', value: formatDuration(ran) });
  return rows;
}

// ------------------------------------------------------------------------------------------------ polling schedule

/** Wait before the next status request: 500, 800, 1280 ... ms, capped at 5 s. */
export function nextPollDelayMs(attempt: number): number {
  const n = Number.isFinite(attempt) ? Math.max(0, attempt) : 0;
  return Math.min(5000, Math.round(500 * 1.6 ** n));
}

export interface PollSnapshot {
  readonly data: RunRecord | undefined;
  readonly error: unknown;
  readonly dataUpdateCount: number;
  readonly errorUpdateCount: number;
}

const TRANSIENT_KINDS: readonly string[] = ['network', 'unavailable', 'server', 'rate_limited'];

/**
 * React Query `refetchInterval` for one run: keep asking while queued or running, wait out a transient failure, stop on
 * a final or unrecognised status and on an error that will not fix itself. The backoff counts answers received.
 */
export function pollInterval(s: PollSnapshot): number | false {
  const attempt = Math.max(0, s.dataUpdateCount + s.errorUpdateCount - 1);
  if (s.error !== null && s.error !== undefined) {
    return isApiError(s.error) && TRANSIENT_KINDS.includes(s.error.kind) ? nextPollDelayMs(attempt) : false;
  }
  if (s.data === undefined) return false;
  return describeStatus(s.data.status).polling ? nextPollDelayMs(attempt) : false;
}

// ------------------------------------------------------------------------------------------------ run state

export type RunState =
  | { kind: 'submitting' }
  | { kind: 'invalid_response'; reason: 'run_id_mismatch' }
  | { kind: 'status'; status: StatusId };

/** `null` = nothing known yet. A record for another run is `invalid_response` and is not displayed. */
export function runStateOf(input: { submitting: boolean; record: RunRecord | null; expectedId: string | null }): RunState | null {
  if (input.submitting) return { kind: 'submitting' };
  if (input.record === null) return null;
  if (input.expectedId !== null && input.record.run_id !== input.expectedId) return { kind: 'invalid_response', reason: 'run_id_mismatch' };
  return { kind: 'status', status: describeStatus(input.record.status).id };
}

export type Verified = { ok: true; result: RunResult } | { ok: false; reason: 'run_id_mismatch' | 'scenario_mismatch' };

/** The result is shown only if it names this run and, when a status record is known, the scenario that record named. */
export function verifyResult(id: string, record: RunRecord | null, result: RunResult): Verified {
  if (result.run_id !== id || (record !== null && record.run_id !== id)) return { ok: false, reason: 'run_id_mismatch' };
  if (record !== null && result.scenario_id !== record.scenario_id) return { ok: false, reason: 'scenario_mismatch' };
  return { ok: true, result };
}

// ------------------------------------------------------------------------------------------------ request and provenance

/** Descriptor-named overrides move under `parameters`; the body carries only what the person changed. */
export function submitBodyOf(request: ScenarioRunRequest): RunSubmitBody {
  const { scenario_id, ...overrides } = request;
  return Object.keys(overrides).length > 0 ? { scenario_id, parameters: overrides } : { scenario_id };
}

const text = (v: unknown): string | null => (typeof v === 'string' && v.trim() !== '' ? v : null);

/** Provenance from the result itself. Absent origin stays unverified; an unreported carbon flag is not assumed. */
export function runProvenance(result: RunResult): ProvenanceInput {
  const p = result.provenance ?? null;
  const real = p?.carbon_data_is_real ?? result.outputs?.carbon_data_is_real;
  return {
    source: { kind: 'run-result' },
    origin: text(p?.origin),
    scenarioId: result.scenario_id,
    runId: result.run_id,
    weatherSource: text(p?.weather_source),
    plantKind: text(p?.plant),
    physicsVersion: text(p?.physics_version),
    modelVersion: text(p?.model_version),
    inputsFallback: typeof real === 'boolean' ? (real ? [] : ['carbon']) : null,
    serverTime: result.ended_at ?? null,
  };
}
