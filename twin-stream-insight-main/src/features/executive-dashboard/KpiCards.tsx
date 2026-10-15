import { useMemo, type ReactNode } from "react";
import { FlaskConical, Info, Clock } from "lucide-react";
import type { SlotWidgetProps } from "../types";
import { safeMessageFor } from "@/api/apiError";
import type { WhatIfResponse } from "@/api/apiClient";
import { StateNotice } from "@/state/StateBoundary";
import { AnimatedNumber } from "./AnimatedNumber";
import { Spark } from "./Sparkline";
import { NOT_MEASURED, carbonKpi, itEnergyKpi, pueKpi, savingsKpi, totalEnergyKpi, type KpiView } from "./kpis";
import { useFeedLive, useModelRun, useSavings } from "./useExecData";
import { useLiveSeries } from "./liveStore";
import type { WhatIfResult } from "@/hooks/useWhatIf";

function Card({ kpi, spark, lastKnown }: { kpi: KpiView; spark?: ReactNode; lastKnown?: boolean }) {
  return (
    <li className="card-grid-glow rounded-lg p-4 space-y-2 list-none" data-kpi={kpi.id} data-measured={kpi.value !== null}>
      <p className="text-xs uppercase tracking-wider text-muted-foreground">{kpi.label}</p>
      {kpi.value === null ? (
        <div className="space-y-1">
          <p className="font-mono text-lg font-bold text-foreground" data-testid={`kpi-${kpi.id}-value`}>{NOT_MEASURED}</p>
          {kpi.reason && <p className="text-[11px] text-muted-foreground">{kpi.reason}</p>}
        </div>
      ) : (
        <div className="flex items-end gap-2">
          <span className="font-mono text-2xl font-bold text-foreground" data-testid={`kpi-${kpi.id}-value`}>
            <AnimatedNumber value={kpi.value} decimals={kpi.decimals} />
          </span>
          {kpi.unit && <span className="mb-0.5 text-sm text-muted-foreground">{kpi.unit}</span>}
        </div>
      )}
      {kpi.direction && <p className="text-xs text-foreground">{kpi.direction}</p>}
      {lastKnown && (
        <p className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
          <Clock aria-hidden="true" className="h-3 w-3" /> Last known value: the live feed is not current.
        </p>
      )}
      {spark}
      {kpi.caveat && (
        <p className="inline-flex items-start gap-1 rounded border border-dashed border-muted-foreground/50 px-1.5 py-0.5 text-[11px] text-foreground">
          <Info aria-hidden="true" className="mt-px h-3 w-3 shrink-0" /> {kpi.caveat}
        </p>
      )}
      <p className="text-[11px] leading-snug text-muted-foreground">{kpi.basis}</p>
    </li>
  );
}

function Pending({ label, children }: { label: string; children: ReactNode }) {
  return (
    <li className="card-grid-glow rounded-lg p-4 list-none" data-kpi-state="pending">
      <p className="text-xs uppercase tracking-wider text-muted-foreground">{label}</p>
      <div className="mt-2">{children}</div>
    </li>
  );
}

/** One what-if-derived card, or the loading / error state that stands in for it. */
function modelCard(run: WhatIfResult, label: string, build: (w: WhatIfResponse | null) => KpiView, spark?: ReactNode): ReactNode {
  if (run.status === "loading") {
    return (
      <Pending key={label} label={label}>
        <p role="status" className="text-xs text-muted-foreground">Loading the 24 h model run…</p>
      </Pending>
    );
  }
  if (run.status === "unauthorized") {
    return (
      <Pending key={label} label={label}>
        <StateNotice kind="unauthorized" text="The model run is not available to this session." block={false} />
      </Pending>
    );
  }
  if (run.status === "error") {
    return (
      <Pending key={label} label={label}>
        <StateNotice kind="error" text={safeMessageFor(run.kind)} block={false} />
      </Pending>
    );
  }
  const kpi = build(run.data);
  return <Card key={label} spark={kpi.value === null ? undefined : spark} kpi={run.refreshFailed ? { ...kpi, caveat: kpi.caveat ?? "Last refresh failed: showing the earlier result." } : kpi} />;
}

export default function KpiCards(_props: SlotWidgetProps) {
  const samples = useLiveSeries();
  const live = useFeedLive();
  const run = useModelRun();
  const savings = useSavings();
  const latest = samples[samples.length - 1] ?? null;
  const whatIf = run.status === "ready" ? run.data : null;

  const pueSeries = useMemo(() => samples.map((s) => s.pue), [samples]);
  const itSeries = useMemo(() => samples.map((s) => s.itKw), [samples]);
  const totalSeries = useMemo(() => samples.map((s) => s.totalKw), [samples]);
  const carbonSeries = useMemo(() => samples.flatMap((s) => (s.carbonGPerKwh === null ? [] : [s.carbonGPerKwh])), [samples]);
  const pueCard = (
    <Card
      key="pue"
      kpi={pueKpi(latest, whatIf)}
      lastKnown={latest !== null && !live}
      spark={latest ? <Spark values={pueSeries} label="PUE" unit="" /> : undefined}
    />
  );

  const savingsCard =
    savings.state === "loading" ? (
      <Pending key="savings" label="Savings vs baseline controller">
        <p role="status" className="text-xs text-muted-foreground">Loading the policy-evaluation report…</p>
      </Pending>
    ) : (
      <Card key="savings" kpi={savingsKpi(savings.facts, savings.reason)} />
    );

  return (
    <section aria-labelledby="exec-kpi-heading" className="col-span-full space-y-2" data-testid="exec-kpis">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="exec-kpi-heading" className="text-sm font-semibold text-foreground">Executive summary</h2>
        <p className="inline-flex items-center gap-1 rounded border border-dashed border-muted-foreground/50 px-1.5 py-0.5 text-[11px] text-muted-foreground">
          <FlaskConical aria-hidden="true" className="h-3 w-3" /> Simulated data. Energy and carbon are model estimates.
        </p>
      </div>
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5 p-0 m-0">
        {pueCard}
        {modelCard(run, "IT energy", itEnergyKpi, <Spark values={itSeries} label="Live IT power" unit=" kW" />)}
        {modelCard(run, "Total energy", totalEnergyKpi, <Spark values={totalSeries} label="Live total power" unit=" kW" />)}
        {modelCard(run, "Carbon", carbonKpi, <Spark values={carbonSeries} label="Live grid carbon intensity" unit=" gCO₂/kWh" />)}
        {savingsCard}
      </ul>
    </section>
  );
}
