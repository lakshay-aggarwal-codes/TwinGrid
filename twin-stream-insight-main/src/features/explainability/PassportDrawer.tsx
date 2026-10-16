import { useState } from "react";
import { AlertTriangle, Archive, CheckCircle2, FlaskConical, HelpCircle, ShieldAlert, XCircle, type LucideIcon } from "lucide-react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { StateBoundary } from "@/state/StateBoundary";
import { SYNTHETIC_LABEL, formatMetric, kindLabel, metricLabel, modelsFor, statusView, type Passport, type PassportModel, type StatusIcon } from "./model";
import { usePassport } from "./usePassport";

const ICON: Record<StatusIcon, LucideIcon> = {
  promoted: CheckCircle2,
  candidate: FlaskConical,
  quarantined: ShieldAlert,
  rejected: XCircle,
  retired: Archive,
  unknown: HelpCircle,
};
// The status is carried by the icon shape, the words and the border style, never by colour alone.
const BORDER: Record<StatusIcon, string> = {
  promoted: "border-solid",
  candidate: "border-dashed",
  quarantined: "border-solid border-destructive/50",
  rejected: "border-solid border-destructive/50",
  retired: "border-dotted",
  unknown: "border-dotted",
};

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3 text-xs">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className="break-words text-right">{children}</dd>
    </div>
  );
}

export function ModelCard({ model }: { model: PassportModel }) {
  const status = statusView(model.status);
  const Icon = ICON[status.icon];
  return (
    <div className="space-y-3 pt-2" data-testid="passport-model" data-kind={model.kind} data-status={model.status}>
      <p data-testid="passport-status" className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs ${BORDER[status.icon]}`}>
        <Icon aria-hidden="true" className="h-3.5 w-3.5" />
        {status.text}
      </p>
      {model.status_reason ? <p className="text-xs text-muted-foreground">{model.status_reason}</p> : null}

      <p data-testid="passport-origin" className="inline-flex items-center gap-1 rounded border border-dashed border-border px-1.5 py-0.5 text-xs">
        <FlaskConical aria-hidden="true" className="h-3.5 w-3.5" />
        Data origin: {model.data_origin}. Every number below is a {SYNTHETIC_LABEL}.
      </p>
      {model.data_origin_basis ? <p className="text-[11px] text-muted-foreground">{model.data_origin_basis}</p> : null}

      <section aria-label="Headline metrics" className="space-y-1">
        <h3 className="text-xs font-semibold">Headline metrics ({model.metrics_label})</h3>
        {model.headline_metrics.length === 0 ? (
          <p className="text-xs text-muted-foreground" data-testid="passport-no-metrics">
            NOT MEASURED: the registry holds no headline metric for this model.
          </p>
        ) : (
          <dl className="space-y-1">
            {model.headline_metrics.map((m) => (
              <Row key={m.name} label={metricLabel(m.name)}>
                <span title={String(m.value)} className="font-mono tabular-nums">
                  {formatMetric(m.value)}
                </span>
              </Row>
            ))}
          </dl>
        )}
      </section>

      {model.evaluation ? (
        <section aria-label="Stored evaluation decision" className="space-y-1 rounded border border-border p-2" data-testid="passport-evaluation">
          <h3 className="text-xs font-semibold">Evaluation decision (as stored)</h3>
          <p className="text-xs">
            Outcome <span className="font-mono">{model.evaluation.outcome}</span>; claim allowed:{" "}
            <span className="font-mono">{model.evaluation.claim_allowed}</span>.
          </p>
          {model.evaluation.reason ? <p className="text-[11px] text-muted-foreground">{model.evaluation.reason}</p> : null}
          <p className="text-[11px] text-muted-foreground">
            Source: {model.evaluation.source}
            {model.evaluation.evaluation_id ? ` (${model.evaluation.evaluation_id})` : ""}.
          </p>
        </section>
      ) : null}

      {model.detector ? (
        <section aria-label="Detector settings" className="space-y-1">
          <h3 className="text-xs font-semibold">Detector</h3>
          <dl className="space-y-1">
            <Row label="Alert threshold">
              <span className="font-mono">{model.detector.threshold.toFixed(4)}</span>
              {typeof model.detector.threshold_percentile === "number" ? ` (percentile ${model.detector.threshold_percentile})` : ""}
            </Row>
            <Row label="Inputs">{model.detector.feature_columns.join(", ")}</Row>
          </dl>
          {model.explanation_method ? <p className="text-[11px] text-muted-foreground">{model.explanation_method}</p> : null}
        </section>
      ) : null}

      <section aria-label="Limitations" className="space-y-1">
        <h3 className="text-xs font-semibold">Limitations</h3>
        <ul className="list-disc space-y-1 pl-4 text-xs">
          {model.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
        <p className="text-[11px] text-muted-foreground">From: {model.limitations_source.join(", ")}</p>
      </section>

      <section aria-label="Claim boundary" className="space-y-1">
        <h3 className="text-xs font-semibold">Claim boundary</h3>
        <p className="text-xs" data-testid="passport-boundary">
          {model.claim_boundary}
        </p>
      </section>

      <dl className="space-y-1 border-t border-border pt-2">
        <Row label="Model id">
          <span className="font-mono">{model.model_id}</span>
        </Row>
        {model.version ? <Row label="Version">{model.version}</Row> : null}
        {model.data_source ? <Row label="Data source">{model.data_source}</Row> : null}
        {model.physics_version ? <Row label="Physics version">{model.physics_version}</Row> : null}
      </dl>
    </div>
  );
}

function Body({ passport, kind, onShowAll }: { passport: Passport; kind: string | null; onShowAll: () => void }) {
  const models = modelsFor(passport, kind);
  return (
    <div className="space-y-3">
      {kind !== null ? (
        <p className="text-xs text-muted-foreground">
          Showing {kindLabel(kind)} only.{" "}
          <button type="button" onClick={onShowAll} className="underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            Show all models
          </button>
        </p>
      ) : null}
      {models.length === 0 ? (
        <p className="text-sm" data-testid="passport-none-for-kind">
          The registry has no {kind ? kindLabel(kind) : "model"} entry.
        </p>
      ) : (
        models.map((m, i) => (
          <details key={m.model_id} open={i === 0} className="rounded-md border border-border p-2" data-testid="passport-details">
            <summary className="cursor-pointer text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              {kindLabel(m.kind)}: {m.name ?? m.model_id}
              {m.version ? ` ${m.version}` : ""} <span className="text-xs font-normal text-muted-foreground">({m.status})</span>
            </summary>
            <ModelCard model={m} />
          </details>
        ))
      )}
    </div>
  );
}

interface Props {
  open: boolean;
  kind: string | null;
  onClose: () => void;
}

/** The Model Passport drawer. Fetches only while open. Not a certification: it restates the registry and the model cards. */
export function PassportDrawer({ open, kind, onClose }: Props) {
  const { state, refetch } = usePassport(open);
  const [showAllFor, setShowAllFor] = useState<string | null>(null);
  const effectiveKind = showAllFor === kind ? null : kind;
  return (
    <Sheet
      open={open}
      onOpenChange={(o) => {
        if (o) return;
        setShowAllFor(null);
        onClose();
      }}
    >
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md" data-testid="passport-drawer">
        <SheetHeader>
          <SheetTitle>Model passport</SheetTitle>
          <SheetDescription>
            What each model is, how it was trained and what it may be used to claim. Every model here was trained on simulator data, so its metrics are{" "}
            {SYNTHETIC_LABEL}s, not statements about a real facility.
          </SheetDescription>
        </SheetHeader>
        <div className="mt-4">
          <StateBoundary state={state} onRetry={refetch} messages={{ loading: "Loading the model passport…", empty: "The model registry holds no models." }}>
            {(passport) => <Body passport={passport} kind={effectiveKind} onShowAll={() => setShowAllFor(kind)} />}
          </StateBoundary>
        </div>
        <p className="mt-4 flex items-start gap-1 text-[11px] text-muted-foreground">
          <AlertTriangle aria-hidden="true" className="mt-0.5 h-3 w-3 shrink-0" />
          Read-only view of models/registry.json, the model cards and the stored evaluation decision.
        </p>
      </SheetContent>
    </Sheet>
  );
}
