import { StateBoundary } from "@/state/StateBoundary";
import { useEquipmentModel } from "./useMaintenance";

/** The existing equipment-health service, shown for what it is: a model's methodology metrics on a proxy dataset. */
export function ModelContext() {
  const { state, refetch } = useEquipmentModel();
  return (
    <section aria-labelledby="mx-model" className="card-grid-glow space-y-2 rounded-lg p-4" data-testid="model-context">
      <h2 id="mx-model" className="text-sm font-semibold text-foreground">Predictive-maintenance model (methodology only)</h2>
      <p className="text-[11px] text-muted-foreground">
        Trained on a proxy dataset, not on this facility. It is not applied to the assets above, so it produces no remaining-life figure here.
      </p>
      <StateBoundary state={state} onRetry={refetch} messages={{ loading: "Reading the model's last training run…" }}>
        {(m) =>
          m.available ? (
            <div className="space-y-1 text-xs text-foreground" data-testid="model-metrics">
              {m.baseline && m.lstm && (
                <p>
                  Held-out proxy data, mean absolute error: baseline {m.baseline.mae.toFixed(1)}, LSTM {m.lstm.mae.toFixed(1)}
                  {m.beats_baseline === undefined ? "" : m.beats_baseline ? " (LSTM better)" : " (LSTM not better than the baseline)"}.
                </p>
              )}
              {m.dataset_caveat && <p className="text-muted-foreground" data-testid="model-caveat">{m.dataset_caveat}</p>}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground" data-testid="model-unavailable">
              No training run is available: remaining-life modelling is NOT MEASURED.
            </p>
          )
        }
      </StateBoundary>
    </section>
  );
}
