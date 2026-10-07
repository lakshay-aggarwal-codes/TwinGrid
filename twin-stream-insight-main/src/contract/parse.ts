/**
 * FE-01 contract layer: the single validated boundary.
 *
 * `parseApi` never throws and never repairs: a payload that violates its schema yields `{ ok: false }`
 * with a ContractError (paths only) and is reported. Callers must treat that as "unavailable", not
 * substitute defaults.
 */
import type { z } from 'zod';
import { reportError } from '@/lib/errorReporter.ts';
import { ContractError, formatPath, type ContractIssue } from './errors';

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: ContractError };

/**
 * Narrowing helpers. This repo compiles with `strict: false`, where `if (!r.ok) r.error` does NOT narrow a
 * discriminated union. Use these (or `r.ok === false`) instead of truthiness checks.
 */
export function isSuccess<T>(r: ApiResult<T>): r is { ok: true; data: T } {
  return r.ok === true;
}
export function isFailure<T>(r: ApiResult<T>): r is { ok: false; error: ContractError } {
  return r.ok === false;
}

export function parseApi<S extends z.ZodTypeAny>(schema: S, data: unknown, context: string): ApiResult<z.output<S>> {
  const parsed = schema.safeParse(data);
  if (parsed.success) return { ok: true, data: parsed.data };
  const issues: ContractIssue[] = parsed.error.issues.map((issue) => ({
    path: formatPath(issue.path),
    code: issue.code,
  }));
  const error = new ContractError(context, issues);
  reportError(`contract.${context}`, error);
  return { ok: false, error };
}
