import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { usePageTitle } from "@/hooks/usePageTitle";
import { StateBoundary } from "@/state/StateBoundary";
import { Controls } from "./Controls";
import { DeltaCards } from "./DeltaCards";
import { SavedPanel } from "./SavedPanel";
import { Tornado } from "./Tornado";
import { downloadText } from "./exportCsv";
import { ExportButtons } from "../reports-export/ExportButtons";
import { WHATIF_EXPORT_COLUMNS } from "./exportColumns";
import { CARBON_FALLBACK_LABEL, ESTIMATE_LABEL, deltasOf, readMetrics } from "./metrics";
import { WATER_STRESS_HELD, defaultInputs, describeInputs, inputsEqual, normalise, type LabInputs, type SetpointRange } from "./model";
import { addSaved, removeSaved, toCsv, type CsvRow, type Snapshot } from "./saved";
import { useDebouncedInputs, useRun, useSavedScenarios, useSetpointRange, useSweep } from "./useLab";
import { parseLabUrl, withLabParams } from "./url";
import type { WhatIfResponse } from "@/api/apiClient";

const snapshotOf = (inputs: LabInputs, r: WhatIfResponse): Snapshot => ({ inputs, metrics: readMetrics(r), carbonIsReal: r.carbon_data_is_real });
const newId = (): string => (typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `s${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`);
const btn = "rounded border border-border bg-background px-2 py-1 text-xs font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/**
 * `/whatif-lab`. Every number is the backend's own 24 h constant-input run; this page only chooses inputs and subtracts.
 * The set-point range is the server's (it depends on the physics), so nothing is shown until it is known.
 */
export default function LabPage() {
  usePageTitle("TwinGrid — What-if lab");
  const range = useSetpointRange();
  return (
    <main className="mx-auto h-full w-full max-w-6xl space-y-4 overflow-y-auto p-4">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-lg font-semibold text-foreground">What-if lab</h1>
        <Link to="/" className="text-xs text-primary underline">Back to live twin</Link>
      </header>
      <StateBoundary state={range.state} onRetry={range.refetch} messages={{ loading: "Reading the set-point range for the running physics…" }}>
        {(r) => <LabBody range={r} />}
      </StateBoundary>
    </main>
  );
}

function LabBody({ range }: { range: SetpointRange }) {
  const location = useLocation();
  const navigate = useNavigate();
  const defaults = useMemo(() => defaultInputs(range), [range]);
  const [{ scenario: initialScenario, baseline: initialBaseline }] = useState(() => parseLabUrl(location.search, range));
  const [inputs, setInputs] = useState<LabInputs>(initialScenario);
  const [baseline, setBaseline] = useState<LabInputs>(initialBaseline);
  const settled = useDebouncedInputs(inputs);
  const pending = !inputsEqual(settled, inputs);

  const scenarioRun = useRun(settled);
  const baselineRun = useRun(baseline);
  const sweep = useSweep();
  const saved = useSavedScenarios();
  const [notice, setNotice] = useState("");

  // The address follows the SETTLED inputs (not every slider tick), so a copied link always matches what is on screen.
  useEffect(() => {
    const next = withLabParams(location.search, { scenario: settled, baseline }, range);
    if (next !== location.search) navigate({ search: next }, { replace: true });
    // `location.search` is read, not a trigger: the effect writes it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settled, baseline, navigate, range]);

  const baseSnap = baselineRun.state.status === "ready" ? snapshotOf(baseline, baselineRun.state.data) : null;
  const curSnap = scenarioRun.state.status === "ready" ? snapshotOf(settled, scenarioRun.state.data) : null;

  const say = useCallback((text: string) => {
    setNotice(text);
    window.setTimeout(() => setNotice(""), 4000);
  }, []);

  const shareUrl = useMemo(() => `${window.location.origin}${window.location.pathname}${withLabParams("", { scenario: settled, baseline }, range)}`, [settled, baseline, range]);
  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      say("Link copied.");
    } catch {
      say("Could not copy; copy the address bar instead.");
    }
  };
  const exportRows: CsvRow[] = [];
  if (baseSnap) exportRows.push({ name: "Baseline", kind: "baseline", snap: baseSnap });
  if (curSnap) exportRows.push({ name: "Current", kind: "current", snap: curSnap });
  for (const s of saved.list) exportRows.push({ name: s.name, kind: "saved", snap: s });
  const exportCsv = () => {
    downloadText("twingrid-whatif.csv", toCsv(exportRows));
    say("CSV downloaded.");
  };
  const save = (name: string) => {
    if (!curSnap) return;
    const r = addSaved(saved.list, name, curSnap, newId);
    if (r.ok === false) {
      say(r.reason === "full" ? "The saved list is full: delete one first." : "Give the scenario a name.");
      return;
    }
    saved.set(r.list);
    say("Saved.");
  };

  return (
    <div className="space-y-4">
      <p className="rounded border border-dashed border-border px-2 py-1 text-xs text-foreground" data-testid="lab-estimate-label">
        <strong>Results are a {ESTIMATE_LABEL}.</strong> Each figure is one isolated 24 h run of the twin at constant inputs (water stress held at {WATER_STRESS_HELD}); it is not a forecast, is not a measurement, and nothing is stored or changed on the facility.
      </p>

      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Export what-if results">
        <ExportButtons
          label="what-if results"
          formats={["json"]}
          columns={WHATIF_EXPORT_COLUMNS}
          rows={exportRows}
          notes={[`Results are a ${ESTIMATE_LABEL}.`, ...(exportRows.some((r) => !r.snap.carbonIsReal) ? [CARBON_FALLBACK_LABEL] : [])]}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
        <div className="space-y-3">
          <Controls inputs={inputs} range={range} onChange={setInputs} pending={pending} />
          <div className="flex flex-wrap gap-2">
            <button type="button" className={btn} onClick={() => setInputs(defaults)} disabled={inputsEqual(inputs, defaults)}>Reset inputs</button>
            <button type="button" className={btn} onClick={() => setBaseline(settled)} disabled={inputsEqual(baseline, settled)}>Use these inputs as baseline</button>
            <button type="button" className={btn} onClick={() => setBaseline(defaults)} disabled={inputsEqual(baseline, defaults)}>Baseline = default inputs</button>
          </div>
          <p className="text-[11px] text-muted-foreground" data-testid="lab-baseline-desc">Baseline: {describeInputs(baseline)}{inputsEqual(baseline, defaults) ? " (the default what-if)" : ""}.</p>
        </div>

        <div className="space-y-4">
          <StateBoundary state={scenarioRun.state} onRetry={scenarioRun.refetch} messages={{ loading: "Running the scenario…" }}>
            {(scenario) => (
              <StateBoundary state={baselineRun.state} onRetry={baselineRun.refetch} messages={{ loading: "Running the baseline…" }}>
                {(base) => (
                  <div className={pending ? "opacity-70" : undefined} aria-busy={pending}>
                    <DeltaCards deltas={deltasOf(readMetrics(base), readMetrics(scenario))} carbonIsReal={scenario.carbon_data_is_real} baselineCarbonIsReal={base.carbon_data_is_real} />
                  </div>
                )}
              </StateBoundary>
            )}
          </StateBoundary>
          <Tornado current={settled} requestedFor={sweep.for} result={sweep.result} onRun={() => sweep.request(settled)} />
        </div>
      </div>

      <SavedPanel
        baseline={baseSnap}
        current={curSnap}
        saved={saved.list}
        storageOk={saved.storageOk}
        onSave={save}
        onRemove={(id) => saved.set(removeSaved(saved.list, id))}
        onLoad={(i) => setInputs(normalise(i, range))}
        onUseAsBaseline={(i) => setBaseline(normalise(i, range))}
        onExport={exportCsv}
        onCopyLink={copyLink}
        notice={notice}
      />
    </div>
  );
}
