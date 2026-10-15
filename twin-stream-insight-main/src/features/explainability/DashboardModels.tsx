import { ModelPassportButton } from "./ModelPassportButton";
import { SYNTHETIC_LABEL, kindLabel } from "./model";

const KINDS = ["anomaly", "forecaster", "ppo"] as const;

/** Slot `dashboard`: one place to open the passport of each model kind, with the claim boundary in one sentence. */
export default function DashboardModels() {
  return (
    <section aria-label="Models in this twin" data-testid="dashboard-models" className="card-grid-glow rounded-lg p-4 space-y-2 md:col-span-2 xl:col-span-1">
      <h3 className="text-xs uppercase tracking-wider text-muted-foreground">Models in this twin</h3>
      <p className="text-xs text-muted-foreground">
        All three were trained on simulator data, so their metrics are {SYNTHETIC_LABEL}s. Open a passport for status, limitations and what may be claimed.
      </p>
      <ul className="flex flex-wrap gap-2">
        {KINDS.map((k) => (
          <li key={k}>
            <ModelPassportButton kind={k} label={kindLabel(k)} />
          </li>
        ))}
      </ul>
    </section>
  );
}
