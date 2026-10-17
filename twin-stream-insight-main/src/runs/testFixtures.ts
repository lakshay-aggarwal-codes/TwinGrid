/** Test-only: the real G-RUN captures (docs/frontend/contracts/G-RUN.capture-*.json), byte-identical copies. */
import type { RunRecord, RunResult } from './schema';

const pick = <T,>(mods: Record<string, unknown>): T => Object.values(mods)[0] as T;

export const SUBMIT = pick<RunRecord>(import.meta.glob('./fixtures/submit.json', { eager: true, import: 'default' }));
export const QUEUED = pick<RunRecord>(import.meta.glob('./fixtures/status-queued.json', { eager: true, import: 'default' }));
export const COMPLETED = pick<RunRecord>(import.meta.glob('./fixtures/status-completed.json', { eager: true, import: 'default' }));
export const FAILED_FORCED = pick<RunRecord>(import.meta.glob('./fixtures/status-failed-forced.json', { eager: true, import: 'default' }));
export const RESULT = pick<RunResult>(import.meta.glob('./fixtures/result.json', { eager: true, import: 'default' }));

export const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
