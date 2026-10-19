import { useId, useState } from "react";
import { usePageTitle } from "@/hooks/usePageTitle";
import { useSharedSimulation } from "@/hooks/simulationContext";
import { Input } from "@/components/ui/input";
import { StateBoundary } from "@/state/StateBoundary";
import { ESTIMATE_LABEL, STATUS_CUE, VERDICT_TEXT, fmt, parsePlan, rows, verdictSentence, type PlanErrors } from "./model";
import { planStore, usePlan } from "./planStore";
import { useCapacity } from "./useCapacity";

const BTN =
  "rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/**
 * `/capacity`: facility headroom (power, cooling, thermal margin) now and with N more racks at X kW each, as a table and
 * a verdict. Model-based estimate on simulated data; the scenario is the current simulation settings. The 3D overlay
 * for the same plan is switched on from the Live Twin's facility view controls.
 */
export default function CapacityPage() {
  usePageTitle("Capacity planner");
  const uid = useId();
  const { config } = useSharedSimulation();
  const plan = usePlan();
  const [racks, setRacks] = useState(String(plan.addRacks));
  const [kw, setKw] = useState(String(plan.kwPerRack));
  const [errors, setErrors] = useState<PlanErrors>({});
  const { state, refetch } = useCapacity(config, plan);

  const apply = (e: { preventDefault: () => void }) => {
    e.preventDefault();
    const r = parsePlan(racks, kw);
    if (!r.ok) {
      setErrors(r.errors);
      return;
    }
    setErrors({});
    planStore.set(r.plan);
  };

  return (
    <main className="mx-auto max-w-5xl space-y-4 p-4" data-testid="capacity-page">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold text-foreground">Capacity planner</h1>
        <p className="text-sm text-muted-foreground">
          How much power, cooling and thermal headroom the modelled facility has, and whether more racks fit. {ESTIMATE_LABEL} on simulated data: not a design sign-off.
        </p>
      </header>

      <section aria-label="What-if plan" className="card-grid-glow space-y-3 rounded-lg p-4">
        <h2 className="text-xs uppercase tracking-wider text-muted-foreground">Add racks</h2>
        <form onSubmit={apply} className="flex flex-wrap items-start gap-3" noValidate>
          <div className="space-y-1">
            <label htmlFor={`${uid}-racks`} className="text-xs font-medium text-foreground">
              Racks to add
            </label>
            <Input id={`${uid}-racks`} inputMode="numeric" value={racks} onChange={(e) => setRacks(e.target.value)} aria-invalid={errors.racks ? true : undefined} aria-describedby={errors.racks ? `${uid}-racks-err` : undefined} className="w-28" />
            {errors.racks && (
              <p id={`${uid}-racks-err`} role="alert" className="text-[11px] text-destructive-text">
                {errors.racks}
              </p>
            )}
          </div>
          <div className="space-y-1">
            <label htmlFor={`${uid}-kw`} className="text-xs font-medium text-foreground">
              Power per rack (kW)
            </label>
            <Input id={`${uid}-kw`} inputMode="decimal" value={kw} onChange={(e) => setKw(e.target.value)} aria-invalid={errors.kw ? true : undefined} aria-describedby={errors.kw ? `${uid}-kw-err` : undefined} className="w-28" />
            {errors.kw && (
              <p id={`${uid}-kw-err`} role="alert" className="text-[11px] text-destructive-text">
                {errors.kw}
              </p>
            )}
          </div>
          <button type="submit" className={`${BTN} mt-5`}>
            Evaluate
          </button>
        </form>
        <p className="text-[11px] text-muted-foreground" data-testid="capacity-scenario">
          Scenario: the current simulation settings (utilisation {config.serverUtil}%, outside {config.outsideTemp} °C, cooling mode {config.coolingMode}). Added racks are extra IT load on the existing cooling plant and air handling.
        </p>
      </section>

      <StateBoundary state={state} onRetry={refetch} messages={{ loading: "Running the twin for the plan…" }}>
        {(c, meta) => {
          const table = rows(c);
          return (
            <div className="space-y-3" aria-busy={meta.refreshFailed || undefined}>
              <p
                className="rounded-lg border border-border p-3 text-base font-semibold text-foreground"
                data-testid="capacity-verdict"
                data-verdict={c.verdict}
              >
                {VERDICT_TEXT[c.verdict]}
                <span className="ml-2 text-sm font-normal text-muted-foreground">{verdictSentence(c)}</span>
              </p>
              <p className="rounded border border-dashed border-border px-2 py-1 text-[11px] text-foreground" data-testid="capacity-label">
                <strong>{c.label}.</strong> Origin: {c.origin}. {c.limits_note}
              </p>

              <div className="overflow-x-auto">
                <table className="w-full min-w-[34rem] text-left text-xs" data-testid="capacity-table">
                  <caption className="sr-only">Headroom now and with the plan</caption>
                  <thead>
                    <tr className="border-b border-border text-muted-foreground">
                      <th scope="col" className="py-1 pr-3">Measure</th>
                      <th scope="col" className="py-1 pr-3">Limit</th>
                      <th scope="col" className="py-1 pr-3">Now</th>
                      <th scope="col" className="py-1 pr-3">With plan</th>
                      <th scope="col" className="py-1">Plan status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {table.map((r) => {
                      const cue = STATUS_CUE[r.planStatus];
                      return (
                        <tr key={r.key} className="border-b border-border/60" data-testid={`capacity-row-${r.key}`}>
                          <th scope="row" className="py-1 pr-3 font-medium text-foreground">{r.label}</th>
                          <td className="py-1 pr-3 font-mono">{r.limit === null ? "—" : fmt(r.limit, r.unit)}</td>
                          <td className="py-1 pr-3 font-mono">{fmt(r.now, r.unit)}</td>
                          <td className="py-1 pr-3 font-mono">{fmt(r.withPlan, r.unit)}</td>
                          <td className="py-1" data-status={r.planStatus}>
                            {r.key === "inlet" ? "—" : (
                              <span className="inline-flex items-center gap-1">
                                <span aria-hidden="true" className="font-mono">{cue.glyph}</span>
                                {cue.word}
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <p className="text-xs text-foreground" data-testid="capacity-fit">
                Whole racks of {c.plan.kw_per_rack} kW that fit today by power: {c.racks_that_fit.by_power ?? "not modelled"}; by cooling: {c.racks_that_fit.by_cooling ?? "not modelled"}; limit: {c.racks_that_fit.limit ?? "not modelled"}. {c.racks_that_fit.note}
              </p>
              <details className="text-[11px] text-muted-foreground">
                <summary className="cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">How this is computed</summary>
                <p className="mt-1">{c.basis}</p>
              </details>
            </div>
          );
        }}
      </StateBoundary>
    </main>
  );
}
