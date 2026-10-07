/**
 * FE-01 contract layer: error type.
 *
 * A ContractError describes WHERE a payload broke the contract, never WHAT it contained. It carries
 * issue paths and zod issue codes only -- no received values, no zod messages (zod messages can quote the
 * received value, e.g. "Invalid enum value. Received 'x'"). That makes it safe to hand to `reportError`.
 */

export interface ContractIssue {
  /** Dotted/indexed path inside the payload, e.g. `results[3].pue`. `(root)` for the payload itself. */
  readonly path: string;
  /** zod issue code, e.g. `invalid_type`, `too_small`. Never a message. */
  readonly code: string;
}

const MAX_PATHS_IN_MESSAGE = 5;

export function formatPath(path: ReadonlyArray<string | number>): string {
  if (path.length === 0) return '(root)';
  let out = '';
  for (const seg of path) {
    if (typeof seg === 'number') out += `[${seg}]`;
    else out += out ? `.${seg}` : seg;
  }
  return out;
}

export class ContractError extends Error {
  /** Caller-supplied label for the endpoint/frame (a developer constant, never payload data). */
  readonly context: string;
  readonly issues: readonly ContractIssue[];

  constructor(context: string, issues: readonly ContractIssue[]) {
    const shown = issues
      .slice(0, MAX_PATHS_IN_MESSAGE)
      .map((i) => i.path)
      .join(', ');
    const more = issues.length > MAX_PATHS_IN_MESSAGE ? ` (+${issues.length - MAX_PATHS_IN_MESSAGE} more)` : '';
    super(`Contract violation (${context}): ${issues.length} issue(s) at ${shown}${more}`);
    this.name = 'ContractError';
    this.context = context;
    this.issues = issues;
  }
}
