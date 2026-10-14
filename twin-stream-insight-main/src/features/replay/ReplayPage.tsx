import { Link } from "react-router-dom";
import { usePageTitle } from "@/hooks/usePageTitle";
import { StateBoundary, StateNotice } from "@/state/StateBoundary";
import { isTelemetryHistoryEnabled } from "@/telemetry/history/flag";
import { MEASURANDS } from "@/telemetry/history/model";
import { CompareCard } from "./CompareCard";
import type { LoadedReplay } from "./loader";
import { ReplayBanner } from "./ReplayBanner";
import { ReplayChart } from "./ReplayChart";
import { useReplay } from "./ReplayContext";
import { ReplayKpis } from "./ReplayKpis";
import { ReplayProvider } from "./ReplayProvider";
import { ReplayScene } from "./ReplayScene";
import { Timeline } from "./Timeline";
import { Transport } from "./Transport";

function Charts({ data }: { data: LoadedReplay }) {
  const { state, snapshot } = useReplay();
  const nameOf = (id: string) => MEASURANDS.find((m) => m.id === id)?.label ?? id;
  return (
    <div className="space-y-3">
      {data.failed.length > 0 && <StateNotice kind="incomplete" text={`Could not load: ${data.failed.map(nameOf).join(", ")}. The other measurands are shown.`} />}
      <div className="grid gap-3 md:grid-cols-2" data-testid="replay-charts">
        {data.dataset.series.map((s) => (
          <ReplayChart
            key={s.measurand}
            series={s}
            fromMs={state.fromMs}
            toMs={state.toMs}
            cursorMs={state.cursorMs}
            bMs={state.compareOn ? state.compareBMs : null}
            read={snapshot?.[s.measurand]}
          />
        ))}
      </div>
    </div>
  );
}

function ReplayScreen() {
  usePageTitle("TwinGrid — Replay");
  const { load } = useReplay();
  return (
    <main className="mx-auto h-full w-full max-w-6xl space-y-4 overflow-y-auto p-4">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-lg font-semibold text-foreground">Replay and time travel</h1>
        <Link to="/" className="text-xs text-primary underline">
          Back to live twin
        </Link>
      </header>
      <p className="text-xs text-muted-foreground">
        Scrub through stored telemetry from the telemetry store. Values are simulated unless a sample says otherwise, are shown as the sample at or before the chosen time, and are never interpolated. This page reads
        history only; it does not control a facility.
      </p>
      <ReplayBanner />
      <Transport />
      <Timeline />
      <ReplayKpis />
      <CompareCard />
      <StateBoundary
        state={load.state}
        onRetry={load.refetch}
        messages={{ loading: "Loading stored telemetry…", empty: "No stored telemetry in this window. Choose a longer window or press Refresh window." }}
      >
        {(data) => <Charts data={data} />}
      </StateBoundary>
      <ReplayScene />
    </main>
  );
}

/** `/replay`. Replay state belongs to this page: leaving it returns every other page to its live feed. */
export default function ReplayPage() {
  if (!isTelemetryHistoryEnabled()) {
    return (
      <main className="mx-auto w-full max-w-3xl p-4">
        <p className="text-sm text-muted-foreground" data-testid="replay-disabled">
          Replay needs the telemetry history view, which is turned off in this build.
        </p>
      </main>
    );
  }
  return (
    <ReplayProvider>
      <ReplayScreen />
    </ReplayProvider>
  );
}
