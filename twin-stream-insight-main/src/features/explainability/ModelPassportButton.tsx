import { ShieldCheck } from "lucide-react";
import { openPassport } from "./passportStore";

interface Props {
  /** Model kind to open the passport for (`anomaly`, `forecaster`, `ppo`), or omit for every model. */
  kind?: string;
  label?: string;
  className?: string;
}

/**
 * Opens the Model Passport drawer. It only sets the open state (no query, no provider), so any model-driven widget can
 * carry it; the drawer itself is mounted once by the header widget.
 */
export function ModelPassportButton({ kind, label = "Model passport", className }: Props) {
  return (
    <button
      type="button"
      data-testid="model-passport-button"
      data-kind={kind ?? "all"}
      aria-haspopup="dialog"
      onClick={() => openPassport(kind ?? null)}
      className={
        className ??
        "inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-[11px] font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      }
    >
      <ShieldCheck aria-hidden="true" className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}
