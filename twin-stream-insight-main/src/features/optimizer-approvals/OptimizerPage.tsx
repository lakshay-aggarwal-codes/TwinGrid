import { useMemo, useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { usePageTitle } from "@/hooks/usePageTitle";
import { useSharedSimulation } from "@/hooks/simulationContext";
import { whatIfParams } from "@/hooks/useWhatIf";
import { useFeed } from "@/telemetry/useFeed";
import { PpoPanel } from "./PpoPanel";
import { ProposalsPanel } from "./ProposalsPanel";
import { RecommendationCard } from "./RecommendationCard";
import { ShadowPanel } from "./ShadowPanel";
import type { Context } from "./model";

export default function OptimizerPage() {
  usePageTitle("Optimizer · TwinGrid");
  const { role, username } = useAuth();
  const { config } = useSharedSimulation();
  const inlet = useFeed((v) => (v.freshness.state === "live" ? (v.frame?.value?.server_inlet_temp_C ?? null) : null));
  const [ppoUnavailable, setPpoUnavailable] = useState(false);
  const w = whatIfParams(config);
  const ctx: Context = useMemo(
    () => ({
      utilisation: w.utilisation,
      outside_temp: w.outside_temp,
      water_stress: w.water_stress,
      mode: w.mode,
      chilled_water_temp: w.chilled_water_temp,
      inlet_temp_c: typeof inlet === "number" && Number.isFinite(inlet) ? Math.round(inlet * 10) / 10 : null,
    }),
    [w.utilisation, w.outside_temp, w.water_stress, w.mode, w.chilled_water_temp, inlet],
  );
  return (
    <main aria-labelledby="optimizer-h" className="mx-auto max-w-5xl space-y-4 p-4">
      <header className="space-y-1">
        <h1 id="optimizer-h" className="text-lg font-semibold">
          Optimizer
        </h1>
        <p className="max-w-prose text-xs text-muted-foreground">
          Set-point recommendations for the simulated facility, with a sandbox, an approval step and the shadow-mode comparison. Everything here
          is simulator output. The conditions come from the Live page controls (utilisation {Math.round(ctx.utilisation * 100)}%, outside{" "}
          {ctx.outside_temp} °C, water stress {ctx.water_stress}).
        </p>
      </header>
      <PpoPanel role={role} onUnavailable={setPpoUnavailable} />
      <RecommendationCard ctx={ctx} role={role} ppoUnavailable={ppoUnavailable} />
      <ProposalsPanel role={role} username={username} />
      <ShadowPanel role={role} />
    </main>
  );
}
