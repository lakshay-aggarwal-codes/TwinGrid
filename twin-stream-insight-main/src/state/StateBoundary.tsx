import type { ReactNode } from "react";
import { StatusMessage } from "@/components/shell/StatusMessage";
import { uiStateOf, type DataState, type UiStateKind } from "./dataState";
import {
  STALE_REFRESH_FAILED_LABEL,
  STATE_COPY,
  UNAUTHORIZED_COPY,
  errorCopyFor,
} from "./errorCopy";

interface StateNoticeProps {
  kind: UiStateKind;
  /** Feature-specific wording. Omit for the generic default from `errorCopy.ts`. */
  text?: string;
  title?: string;
  action?: { label: string; onClick: () => void };
  block?: boolean;
}

/** Render a single state from the vocabulary. Use for states that are not derived from a `DataState` (stale, disconnected, unsupported_scenario...). */
export function StateNotice({ kind, text, title, action, block }: StateNoticeProps) {
  const copy = STATE_COPY[kind];
  return (
    <StatusMessage kind={kind} title={title ?? copy.title} action={action} block={block}>
      {text ?? copy.description}
    </StatusMessage>
  );
}

export interface ReadyMeta {
  readonly refreshFailed: boolean;
}

interface StateBoundaryProps<T> {
  state: DataState<T>;
  /** Rendered only for `ready`. Receives the data; notices for stale/incomplete are drawn above it by the boundary. */
  children: (data: T, meta: ReadyMeta) => ReactNode;
  /** Offered for retryable errors and for a failed refresh. */
  onRetry?: () => void;
  block?: boolean;
  /** Optional feature wording for the states that have no backend-driven copy. */
  messages?: Partial<Record<"loading" | "empty" | "not_run", string>>;
}

/**
 * Renders the right component for a `DataState<T>`; screens do not hand-roll these states.
 * User text comes only from `errorCopy.ts`: no `Error.message`, backend `detail` or body text can reach the DOM.
 */
export function StateBoundary<T>({ state, children, onRetry, block = true, messages }: StateBoundaryProps<T>) {
  const retry = onRetry ? { label: "Try again", onClick: onRetry } : undefined;

  switch (state.status) {
    case "loading":
    case "empty":
    case "not_run":
      return <StateNotice kind={state.status} text={messages?.[state.status]} block={block} />;

    case "unauthorized": {
      const copy = UNAUTHORIZED_COPY[state.reason];
      // No retry action: 401/403 never loop. Sign-in is handled by the auth gate.
      return <StateNotice kind="unauthorized" title={copy.title} text={copy.description} block={block} />;
    }

    case "error": {
      const kind = uiStateOf(state) as UiStateKind;
      if (kind === "unavailable_model") {
        return <StateNotice kind="unavailable_model" block={block} />;
      }
      const copy = errorCopyFor(state.kind);
      return (
        <StateNotice
          kind={kind}
          title={copy.title}
          text={copy.description}
          action={copy.retryable ? retry : undefined}
          block={block}
        />
      );
    }

    default: {
      const refreshFailed = state.refreshFailed === true;
      return (
        <>
          {refreshFailed ? (
            <StateNotice kind="stale" title={STALE_REFRESH_FAILED_LABEL} text="Showing the last result received." action={retry} />
          ) : state.freshness === "stale" ? (
            <StateNotice kind="stale" />
          ) : state.freshness === "disconnected" ? (
            <StateNotice kind="disconnected" />
          ) : null}
          {state.incomplete && state.incomplete.length > 0 && (
            <StateNotice kind="incomplete" text={`Not reported: ${state.incomplete.join(", ")}.`} />
          )}
          {children(state.data, { refreshFailed })}
        </>
      );
    }
  }
}
