import { Component, Suspense, type ErrorInfo, type ReactNode } from "react";
import { useRole } from "@/hooks/useAuth.ts";
import { reportError } from "@/lib/errorReporter";
import { featureRegistry, type FeatureRegistry } from "./registry";
import type { SlotName } from "./types";

interface BoundaryProps {
  scope: string;
  children: ReactNode;
}

/** One widget failing renders a plain notice in its place; its siblings and the host are untouched. */
class SlotBoundary extends Component<BoundaryProps, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error, _info: ErrorInfo) {
    reportError(`Slot:${this.props.scope}`, error);
  }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <p role="status" data-testid="slot-widget-error" className="text-xs text-muted-foreground">
        This widget could not be shown.
      </p>
    );
  }
}

interface SlotProps {
  name: SlotName;
  /** Passed to every widget as `context`. */
  context?: Readonly<Record<string, unknown>>;
  className?: string;
  /** Tests only. */
  registry?: FeatureRegistry;
}

const NO_CONTEXT: Readonly<Record<string, unknown>> = Object.freeze({});

/** A host point: renders the widgets features registered for `name` (role-filtered, by `order`), or nothing at all. */
export function Slot({ name, context = NO_CONTEXT, className, registry = featureRegistry }: SlotProps) {
  const { role } = useRole();
  const widgets = registry.slotWidgets(name, role);
  if (widgets.length === 0) return null;
  return (
    <div data-slot={name} className={className}>
      {widgets.map(({ key, component: Widget }) => (
        <SlotBoundary key={key} scope={`${name}/${key}`}>
          <Suspense fallback={<span role="status" className="sr-only">Loading…</span>}>
            <Widget context={context} />
          </Suspense>
        </SlotBoundary>
      ))}
    </div>
  );
}
