import { useState } from "react";
import { Settings2 } from "lucide-react";
import { useSharedSimulation } from "@/hooks/simulationContext";
import { StateBoundary } from "@/state/StateBoundary";
import { TariffDrawer } from "./TariffDrawer";
import { formatMoney, savingsWording } from "./tariff";
import { useEconomics } from "./useEconomics";
import { useTariff } from "./useTariff";

const BTN =
  "inline-flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** Slot `dashboard`: cost of the current scenario's simulated day under an illustrative tariff, and the saving against the default baseline. */
export default function EconomicsCard() {
  const { config } = useSharedSimulation();
  const { tariff, storageOk, save, reset } = useTariff();
  const [open, setOpen] = useState(false);
  const { state, refetch } = useEconomics(config, tariff);

  return (
    <section aria-label="Energy cost" data-testid="economics-card" className="card-grid-glow space-y-2 rounded-lg p-4 md:col-span-2 xl:col-span-1">
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-xs uppercase tracking-wider text-muted-foreground">Energy cost (one simulated day)</h2>
        <button type="button" className={BTN} onClick={() => setOpen(true)} aria-haspopup="dialog">
          <Settings2 className="h-3.5 w-3.5" aria-hidden="true" /> Tariff settings
        </button>
      </div>
      <StateBoundary state={state} onRetry={refetch} messages={{ loading: "Costing the scenario…" }}>
        {(e, meta) => {
          const total = e.scenario.cost.total_cost;
          const w = savingsWording(e.savings.total_cost, e.savings.total_pct, e.currency);
          return (
            <div className="space-y-2" aria-busy={meta.refreshFailed || undefined}>
              <p className="text-2xl font-semibold text-foreground" data-testid="economics-total">{formatMoney(total, e.currency)}</p>
              <p className="rounded border border-dashed border-border px-2 py-1 text-[11px] text-foreground" data-testid="economics-label">
                <strong>{e.label}.</strong> {e.estimate_label}. {e.currency_note}
              </p>
              <dl className="grid grid-cols-[1fr_auto] gap-x-3 text-xs">
                <dt className="text-muted-foreground">Energy ({e.scenario.cost.energy_kwh.toFixed(0)} kWh)</dt>
                <dd className="font-mono">{formatMoney(e.scenario.cost.energy_cost, e.currency)}</dd>
                <dt className="text-muted-foreground">Demand charge ({e.scenario.cost.peak_kw.toFixed(1)} kW)</dt>
                <dd className="font-mono">{formatMoney(e.scenario.cost.demand_cost, e.currency)}</dd>
              </dl>
              <p className="text-xs font-medium text-foreground" data-testid="economics-savings" data-kind={w.kind}>{w.text}</p>
              {!e.carbon_data_is_real && <p className="text-[11px] text-muted-foreground">Carbon in this twin uses the flat fallback intensity; it does not change this cost.</p>}
              <details className="text-[11px] text-muted-foreground">
                <summary className="cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">How this is computed</summary>
                <p className="mt-1">{e.basis}</p>
              </details>
            </div>
          );
        }}
      </StateBoundary>
      <TariffDrawer open={open} onOpenChange={setOpen} tariff={tariff} storageOk={storageOk} onSave={save} onReset={reset} />
    </section>
  );
}
