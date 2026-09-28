import { Component, type ReactNode } from "react";
import { StatusMessage } from "@/components/shell/StatusMessage";
import { reportError } from "@/lib/errorReporter";

interface Props {
  children: ReactNode;
}
interface State {
  failed: boolean;
}

/**
 * Stage 14: the 3D scene had no error boundary, so a WebGL failure (no GPU
 * context, driver loss, a thrown render error) unmounted the whole page.
 * Now it degrades to the same error pattern as every other panel, with the
 * header, panels and inspector still usable.
 */
export class SceneErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error) {
    reportError("SceneErrorBoundary", error);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="absolute inset-0 flex items-center justify-center p-6">
        <div className="max-w-sm">
          <StatusMessage kind="error" action={{ label: "Reload scene", onClick: () => this.setState({ failed: false }) }}>
            The 3D view failed to render (WebGL may be unavailable). Panels and live readings still work.
          </StatusMessage>
        </div>
      </div>
    );
  }
}
