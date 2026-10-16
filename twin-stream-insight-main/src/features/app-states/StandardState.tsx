import type { ReactNode } from "react";
import type { ApiErrorKind } from "@/api/apiError";
import { StatusMessage } from "@/components/shell/StatusMessage";
import { STATE_COPY, errorCopyFor } from "@/state/errorCopy";
import type { DataState, UiStateKind } from "@/state/dataState";
import { StateBoundary } from "@/state/StateBoundary";
import { PLAIN_COPY } from "./plainCopy";
import { StateSkeleton, type SkeletonVariant } from "./StateSkeleton";

const RETRY_LABEL: Partial<Record<UiStateKind, string>> = { stale: "Refresh", disconnected: "Try again now" };

interface StandardStateProps {
  kind: UiStateKind;
  /** For `error`: which kind of failure, so the wording and whether a retry makes sense come from `errorCopy.ts`. */
  errorKind?: ApiErrorKind;
  /** Shown as a button where trying again can help (never for 401/403 or a validation error). */
  onRetry?: () => void;
  /** Shape of the placeholder while loading. */
  skeleton?: SkeletonVariant;
  /** Feature wording, when the plain default does not fit. */
  children?: ReactNode;
  block?: boolean;
}

/**
 * Task 20: one component for loading, empty, error and stale/offline notices. It builds on the existing StatusMessage
 * (icon + text, never colour alone; role and live-region from the shared vocabulary) and adds a skeleton for loading, a
 * Retry button and plain wording.
 */
export function StandardState({ kind, errorKind, onRetry, skeleton = "lines", children, block = true }: StandardStateProps) {
  if (kind === "loading") return <StateSkeleton variant={skeleton} label={typeof children === "string" ? children : undefined} />;

  const err = kind === "error" && errorKind ? errorCopyFor(errorKind) : null;
  const copy = err ?? PLAIN_COPY[kind] ?? STATE_COPY[kind];
  const retryable = err ? err.retryable : kind !== "empty" && kind !== "not_run" && kind !== "unauthorized";
  const label = RETRY_LABEL[kind] ?? "Try again";

  return (
    <StatusMessage kind={kind} title={copy.title} block={block} action={retryable && onRetry ? { label, onClick: onRetry } : undefined}>
      {children ?? copy.description}
    </StatusMessage>
  );
}

interface StandardBoundaryProps<T> {
  state: DataState<T>;
  onRetry?: () => void;
  skeleton?: SkeletonVariant;
  children: (data: T) => ReactNode;
}

/** StateBoundary with a skeleton for loading. Everything else (errors, stale, incomplete, unauthorized) is the shared boundary's. */
export function StandardBoundary<T>({ state, onRetry, skeleton, children }: StandardBoundaryProps<T>) {
  if (state.status === "loading") return <StateSkeleton variant={skeleton} />;
  return (
    <StateBoundary state={state} onRetry={onRetry}>
      {(data) => children(data)}
    </StateBoundary>
  );
}
