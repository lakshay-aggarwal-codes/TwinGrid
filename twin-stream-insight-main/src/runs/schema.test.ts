import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/errorReporter.ts', () => ({ reportError: vi.fn() }));

import { isFailure, isSuccess, parseApi } from '@/contract';
import { RunRecordSchema, RunResultSchema } from './schema';
import { COMPLETED, FAILED_FORCED, QUEUED, RESULT, SUBMIT, clone } from './testFixtures';

describe('run payloads against the G-RUN captures', () => {
  it.each([
    ['submit', SUBMIT],
    ['queued', QUEUED],
    ['completed', COMPLETED],
    ['failed (forced)', FAILED_FORCED],
  ])('the %s record parses', (_n, body) => {
    expect(isSuccess(parseApi(RunRecordSchema, clone(body), 'GET /api/runs/{id}'))).toBe(true);
  });

  it('the captured result parses and keeps its own run id, provenance and outputs', () => {
    const r = parseApi(RunResultSchema, clone(RESULT), 'GET /api/runs/{id}/result');
    expect(isSuccess(r)).toBe(true);
    if (isSuccess(r)) {
      expect(r.data.run_id).toBe(RESULT.run_id);
      expect(r.data.provenance?.origin).toBe('simulated');
      expect(r.data.provenance?.model_version).toBeNull();
      expect(r.data.outputs?.mean_pue).toBeCloseTo(1.416, 3);
    }
  });

  it('a result without run_id is rejected (stop condition: result shape lacks run_id)', () => {
    const body = clone(RESULT) as unknown as Record<string, unknown>;
    delete body.run_id;
    expect(isFailure(parseApi(RunResultSchema, body, 'GET /api/runs/{id}/result'))).toBe(true);
  });

  it('a record without status or run_id is rejected', () => {
    for (const key of ['status', 'run_id']) {
      const body = clone(QUEUED) as unknown as Record<string, unknown>;
      delete body[key];
      expect(isFailure(parseApi(RunRecordSchema, body, 'GET /api/runs/{id}'))).toBe(true);
    }
  });

  it('an unknown status or failure code still parses and stays the raw string', () => {
    const r = parseApi(RunRecordSchema, { ...clone(FAILED_FORCED), status: 'archived', failure_code: 'segfault' }, 'GET /api/runs/{id}');
    expect(isSuccess(r) && r.data.status).toBe('archived');
    expect(isSuccess(r) && r.data.failure_code).toBe('segfault');
  });

  it('unknown extra fields are tolerated and kept', () => {
    const r = parseApi(RunRecordSchema, { ...clone(QUEUED), progress: 0.5 }, 'GET /api/runs/{id}');
    expect(isSuccess(r) && (r.data as Record<string, unknown>).progress).toBe(0.5);
  });

  it('a non-numeric output is rejected, not coerced', () => {
    const body = clone(RESULT) as unknown as { outputs: Record<string, unknown> };
    body.outputs.mean_pue = '1.4';
    expect(isFailure(parseApi(RunResultSchema, body, 'GET /api/runs/{id}/result'))).toBe(true);
  });

  it('missing optional timestamps stay missing (not defaulted)', () => {
    const body = clone(QUEUED) as unknown as Record<string, unknown>;
    delete body.started_at;
    const r = parseApi(RunRecordSchema, body, 'GET /api/runs/{id}');
    expect(isSuccess(r) && r.data.started_at).toBeUndefined();
  });
});
