import type { RefObject } from 'react';

export interface SummaryError {
  /** id of the field the message is about, so the link can move focus to it */
  fieldId: string;
  message: string;
}

/**
 * Accessible error summary: a focusable role="alert" block listing every problem, each linking to its field.
 * The form focuses it (via `summaryRef`) after a failed submit so screen-reader users hear the whole list once.
 */
export function FormErrorSummary({ errors, summaryRef }: { errors: SummaryError[]; summaryRef: RefObject<HTMLDivElement> }) {
  if (errors.length === 0) return null;
  return (
    <div
      ref={summaryRef}
      role="alert"
      tabIndex={-1}
      data-testid="error-summary"
      className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive-text"
    >
      <p className="font-medium">{errors.length === 1 ? 'There is 1 problem with your entry:' : `There are ${errors.length} problems with your entry:`}</p>
      <ul className="mt-1 list-disc space-y-1 pl-5">
        {errors.map((e) => (
          <li key={e.fieldId}>
            <a
              href={`#${e.fieldId}`}
              className="underline underline-offset-2"
              onClick={(ev) => {
                ev.preventDefault();
                document.getElementById(e.fieldId)?.focus();
              }}
            >
              {e.message}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
