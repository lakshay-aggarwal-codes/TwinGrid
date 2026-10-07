import { Component, type ErrorInfo, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { StatusMessage } from "@/components/shell/StatusMessage";
import { reportError } from "@/lib/errorReporter";
import { RENDER_ERROR_COPY } from "./errorCopy";

interface Props {
  /** Where this boundary sits ("app", "route:/analytics"); goes to the reporter, never to the DOM. */
  scope: string;
  children: ReactNode;
  /** When any of these change the boundary clears its error (e.g. the route path). */
  resetKeys?: readonly unknown[];
  /** "reload" for the app root (providers may be what broke); "retry" re-renders the subtree. */
  recovery?: "reload" | "retry";
}
interface State {
  failed: boolean;
}

function keysChanged(a: readonly unknown[] = [], b: readonly unknown[] = []): boolean {
  return a.length !== b.length || a.some((v, i) => !Object.is(v, b[i]));
}

/**
 * FE-03: catches a thrown render, reports it (redacted by `reportError`) and shows generic copy.
 * The thrown error's message never reaches the DOM. The 3D scene keeps its own `SceneErrorBoundary`.
 */
export class AppErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    reportError(`AppErrorBoundary:${this.props.scope}`, error);
    if (info.componentStack) reportError(`AppErrorBoundary:${this.props.scope}:componentStack`, info.componentStack, "warning");
  }

  componentDidUpdate(prev: Props) {
    if (this.state.failed && keysChanged(prev.resetKeys, this.props.resetKeys)) this.setState({ failed: false });
  }

  render() {
    if (!this.state.failed) return this.props.children;
    const reload = this.props.recovery !== "retry";
    return (
      <div className="flex min-h-[50vh] items-center justify-center p-6">
        <div className="max-w-sm">
          <StatusMessage
            kind="error"
            title={RENDER_ERROR_COPY.title}
            action={
              reload
                ? { label: "Reload page", onClick: () => window.location.reload() }
                : { label: "Try again", onClick: () => this.setState({ failed: false }) }
            }
          >
            {RENDER_ERROR_COPY.description}
          </StatusMessage>
        </div>
      </div>
    );
  }
}

/** Per-route boundary: a crash in one route leaves the shell up and clears when the path changes. */
export function RouteErrorBoundary({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  return (
    <AppErrorBoundary scope={`route:${pathname}`} resetKeys={[pathname]} recovery="retry">
      {children}
    </AppErrorBoundary>
  );
}
