import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/apiError';
import { buildProvenance } from '@/provenance';
import {
  FAILURE_COPY,
  FAILURE_NOT_REPORTED_TEXT,
  FAILURE_UNRECOGNISED_TEXT,
  RUN_STATUSES,
  UNRECOGNISED_STATUS_TEXT,
  describeStatus,
  durationMs,
  durationRows,
  failureText,
  formatDuration,
  knownStatus,
  nextPollDelayMs,
  pollInterval,
  runProvenance,
  runStateOf,
  serverTimeText,
  submitBodyOf,
  timeRows,
  unrecognisedToken,
  verifyResult,
} from './model';
import { COMPLETED, FAILED_FORCED, QUEUED, RESULT, clone } from './testFixtures';

afterEach(() => vi.useRealTimers());

describe('status vocabulary (exactly the backend set)', () => {
  it('knows five statuses and no others', () => {
    expect([...RUN_STATUSES]).toEqual(['queued', 'running', 'completed', 'failed', 'cancelled']);
    expect(knownStatus('unavailable')).toBeNull();
    expect(knownStatus(undefined)).toBeNull();
  });

  it('each status has its own text; failed and cancelled are distinct', () => {
    const texts = RUN_STATUSES.map((s) => describeStatus(s).text);
    expect(new Set(texts).size).toBe(5);
    expect(describeStatus('failed').text).not.toBe(describeStatus('cancelled').text);
  });

  it.each([
    ['queued', false, true],
    ['running', false, true],
    ['completed', true, false],
    ['failed', true, false],
    ['cancelled', true, false],
  ])('%s: terminal=%s polling=%s', (s, terminal, polling) => {
    const v = describeStatus(s);
    expect(v.id).toBe(s);
    expect(v.terminal).toBe(terminal);
    expect(v.polling).toBe(polling);
  });

  it('an unknown status is "Unrecognised status": not terminal, not polled, not mapped onto a known one', () => {
    const v = describeStatus('archived');
    expect(v).toMatchObject({ id: 'unrecognised', text: UNRECOGNISED_STATUS_TEXT, terminal: false, polling: false });
    expect(describeStatus(undefined).id).toBe('unrecognised');
  });

  it('only a short vocabulary-like token of an unknown status is echoed', () => {
    expect(unrecognisedToken('archived')).toBe('archived');
    expect(unrecognisedToken('<script>alert(1)</script>')).toBeNull();
    expect(unrecognisedToken('x'.repeat(80))).toBeNull();
  });
});

describe('failure copy', () => {
  it('maps each backend code to fixed copy and never shows the code itself', () => {
    for (const code of Object.keys(FAILURE_COPY)) {
      expect(failureText(code)).toBe(FAILURE_COPY[code as keyof typeof FAILURE_COPY]);
      expect(failureText(code)).not.toContain(code);
    }
    expect(new Set(Object.values(FAILURE_COPY)).size).toBe(4);
  });

  it('absent and unknown codes are said so', () => {
    expect(failureText(null)).toBe(FAILURE_NOT_REPORTED_TEXT);
    expect(failureText(undefined)).toBe(FAILURE_NOT_REPORTED_TEXT);
    expect(failureText('segfault')).toBe(FAILURE_UNRECOGNISED_TEXT);
    expect(failureText('segfault')).not.toContain('segfault');
  });
});

describe('backend time only', () => {
  it('formats a server timestamp as UTC and rejects an offset-less one', () => {
    expect(serverTimeText('2026-10-09T18:53:00.296111+00:00')).toBe('2026-10-09 18:53:00 UTC');
    expect(serverTimeText('2026-10-09T18:53:00')).toBeNull();
    expect(serverTimeText(null)).toBeNull();
  });

  it('a queued run says why started/ended are empty', () => {
    const rows = Object.fromEntries(timeRows(QUEUED).map((r) => [r.id, r.value]));
    expect(rows).toEqual({ created: '2026-10-09 18:53:00 UTC', started: 'Not started yet', ended: 'Not ended yet' });
  });

  it('a finished run shows its three server times', () => {
    expect(timeRows(COMPLETED).every((r) => r.value.endsWith(' UTC'))).toBe(true);
  });

  it('a terminal run missing a timestamp says "not reported", never blank', () => {
    const rows = timeRows({ ...clone(COMPLETED), ended_at: null });
    expect(rows.find((r) => r.id === 'ended')?.value).toBe('not reported');
  });

  it('an unreadable timestamp says so', () => {
    expect(timeRows({ ...clone(COMPLETED), created_at: 'yesterday' }).find((r) => r.id === 'created')?.value).toBe('unreadable');
  });

  it('durations are differences between backend timestamps', () => {
    const rows = Object.fromEntries(durationRows(COMPLETED).map((r) => [r.id, r.value]));
    expect(rows).toEqual({ waited: '21 ms', ran: '5 ms' });
    expect(durationRows(QUEUED)).toEqual([]);
  });

  it('an impossible or unreadable pair gives no duration', () => {
    expect(durationMs('2026-10-09T18:53:01+00:00', '2026-10-09T18:53:00+00:00')).toBeNull();
    expect(durationMs('x', '2026-10-09T18:53:00+00:00')).toBeNull();
    expect(durationMs(null, null)).toBeNull();
  });

  it('formats short and long durations', () => {
    expect(formatDuration(5)).toBe('5 ms');
    expect(formatDuration(1500)).toBe('1.5 s');
    expect(formatDuration(125_000)).toBe('2 min 5 s');
  });

  it('nothing here reads the browser clock', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2000-01-01T00:00:00Z'));
    const a = [timeRows(QUEUED), durationRows(COMPLETED)];
    vi.setSystemTime(new Date('2040-01-01T00:00:00Z'));
    expect([timeRows(QUEUED), durationRows(COMPLETED)]).toEqual(a);
  });
});

describe('polling schedule', () => {
  it('backs off from 500 ms to a 5 s cap', () => {
    expect([0, 1, 2, 3, 4, 5, 6, 20].map(nextPollDelayMs)).toEqual([500, 800, 1280, 2048, 3277, 5000, 5000, 5000]);
    expect(nextPollDelayMs(-3)).toBe(500);
    expect(nextPollDelayMs(Number.NaN)).toBe(500);
  });

  const snap = (over: Record<string, unknown>) => ({ data: undefined, error: null, dataUpdateCount: 0, errorUpdateCount: 0, ...over }) as Parameters<typeof pollInterval>[0];

  it('keeps polling queued and running, starting at 500 ms and backing off with the number of answers', () => {
    expect(pollInterval(snap({ data: QUEUED, dataUpdateCount: 1 }))).toBe(500);
    expect(pollInterval(snap({ data: QUEUED, dataUpdateCount: 2 }))).toBe(800);
    expect(pollInterval(snap({ data: { ...QUEUED, status: 'running' }, dataUpdateCount: 4 }))).toBe(2048);
    expect(pollInterval(snap({ data: QUEUED, dataUpdateCount: 2, errorUpdateCount: 2 }))).toBe(2048);
  });

  it.each(['completed', 'failed', 'cancelled', 'archived'])('stops on %s', (status) => {
    expect(pollInterval(snap({ data: { ...QUEUED, status } }))).toBe(false);
  });

  it('keeps going through a transient failure and stops on one that will not fix itself', () => {
    for (const kind of ['network', 'unavailable', 'server', 'rate_limited'] as const) {
      expect(pollInterval(snap({ data: QUEUED, error: new ApiError({ kind }) }))).toBeTypeOf('number');
    }
    for (const kind of ['not_found', 'forbidden', 'unauthenticated', 'contract', 'validation'] as const) {
      expect(pollInterval(snap({ data: QUEUED, error: new ApiError({ kind }) }))).toBe(false);
    }
    expect(pollInterval(snap({ error: new Error('boom') }))).toBe(false);
  });
});

describe('run state', () => {
  it('submitting is client-only and wins while a submit is in flight', () => {
    expect(runStateOf({ submitting: true, record: null, expectedId: null })).toEqual({ kind: 'submitting' });
  });

  it('nothing known yet is null; a record is the backend status', () => {
    expect(runStateOf({ submitting: false, record: null, expectedId: 'x' })).toBeNull();
    expect(runStateOf({ submitting: false, record: QUEUED, expectedId: QUEUED.run_id })).toMatchObject({ kind: 'status', status: 'queued' });
    expect(runStateOf({ submitting: false, record: { ...QUEUED, status: 'archived' }, expectedId: null })).toMatchObject({ kind: 'status', status: 'unrecognised' });
  });

  it('a record for another run is an invalid response', () => {
    expect(runStateOf({ submitting: false, record: QUEUED, expectedId: 'someone-else' })).toEqual({ kind: 'invalid_response', reason: 'run_id_mismatch' });
  });
});

describe('result verification', () => {
  it('accepts a result that names the run (and its scenario)', () => {
    expect(verifyResult(RESULT.run_id, COMPLETED, RESULT)).toEqual({ ok: true, result: RESULT });
    expect(verifyResult(RESULT.run_id, null, RESULT).ok).toBe(true);
  });

  it('rejects a result for another run', () => {
    expect(verifyResult(RESULT.run_id, COMPLETED, { ...RESULT, run_id: 'other-run' })).toEqual({ ok: false, reason: 'run_id_mismatch' });
    expect(verifyResult('other-run', COMPLETED, RESULT)).toEqual({ ok: false, reason: 'run_id_mismatch' });
  });

  it('rejects a result for another scenario than the status record', () => {
    expect(verifyResult(RESULT.run_id, COMPLETED, { ...RESULT, scenario_id: 'other-scenario' })).toEqual({ ok: false, reason: 'scenario_mismatch' });
  });
});

describe('submit body', () => {
  it('sends only the scenario id when nothing was overridden', () => {
    expect(submitBodyOf({ scenario_id: 'abc' })).toEqual({ scenario_id: 'abc' });
  });

  it('puts overrides under `parameters` with the descriptor names', () => {
    expect(submitBodyOf({ scenario_id: 'abc', outside_temp: 30, mode: 'hybrid' })).toEqual({ scenario_id: 'abc', parameters: { outside_temp: 30, mode: 'hybrid' } });
  });
});

describe('result provenance', () => {
  it('carries run id, scenario id, versions and weather/plant from the result itself', () => {
    expect(runProvenance(RESULT)).toEqual({
      source: { kind: 'run-result' },
      origin: 'simulated',
      scenarioId: RESULT.scenario_id,
      runId: RESULT.run_id,
      weatherSource: 'constant_input',
      plantKind: 'simulated',
      physicsVersion: '1',
      modelVersion: null,
      inputsFallback: ['carbon'],
      serverTime: RESULT.ended_at,
    });
  });

  it('builds a Simulated, run-result view with the ids, and no claim of reference weather or dataset', () => {
    const view = buildProvenance(runProvenance(RESULT));
    expect(view.origin.state).toBe('simulated');
    expect(view.kind).toBe('run-result');
    expect(view.strip.run).toBe(RESULT.run_id);
    expect(view.strip.scenario).toBe(RESULT.scenario_id);
    expect(view.flags.some((f) => f.id === 'weather')).toBe(false);
    expect(view.flags.some((f) => f.id === 'fallback')).toBe(true);
    expect(view.detail.find((r) => r.id === 'dataset')?.reported).toBe(false);
    expect(view.detail.find((r) => r.id === 'physics')?.value).toBe('1');
  });

  it('an absent origin stays an Unverified source', () => {
    const body = clone(RESULT);
    delete (body.provenance as Record<string, unknown>).origin;
    expect(buildProvenance(runProvenance(body)).origin.state).toBe('unverified');
  });

  it('real carbon data gives no fallback flag; an unreported carbon flag is "not reported", not assumed', () => {
    const real = clone(RESULT);
    (real.provenance as Record<string, unknown>).carbon_data_is_real = true;
    expect(runProvenance(real).inputsFallback).toEqual([]);
    const none = clone(RESULT);
    delete (none.provenance as Record<string, unknown>).carbon_data_is_real;
    delete (none.outputs as Record<string, unknown>).carbon_data_is_real;
    expect(runProvenance(none).inputsFallback).toBeNull();
  });
});

describe('failed fixture', () => {
  it('maps the captured internal_error code to fixed copy', () => {
    expect(failureText(FAILED_FORCED.failure_code)).toBe(FAILURE_COPY.internal_error);
  });
});
