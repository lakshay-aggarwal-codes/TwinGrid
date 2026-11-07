import { useEffect, useState } from "react";
import { RackReadout } from "./RackReadout";
import { sourceFromEnv } from "./apiSource";
import { fixtureSource, type DatasetInfo, type DatasetTelemetrySource } from "./source";
import type { RackViewEnvelope } from "./schemas";

type Load = { status: "loading" } | { status: "ready"; view: RackViewEnvelope } | { status: "error"; message: string };

const message = (e: unknown, fallback: string): string => (e instanceof Error ? e.message : fallback);
const aborted = (e: unknown): boolean => e instanceof Error && e.name === "AbortError";

/** The Task 16 API when VITE_DATASET_ID and VITE_DATASET_FACILITY_ID are set; otherwise the synthetic fixture. */
const defaultSource: DatasetTelemetrySource = sourceFromEnv(import.meta.env as { VITE_DATASET_ID?: string; VITE_DATASET_FACILITY_ID?: string }) ?? fixtureSource;

export interface DatasetTelemetryPageProps {
  source?: DatasetTelemetrySource;
}

/**
 * Individual rack readouts from an imported dataset, kept apart from the simulated facility view: nothing here reads
 * the live feed, the 36 simulated racks, or the facility topology.
 */
export default function DatasetTelemetryPage({ source = defaultSource }: DatasetTelemetryPageProps) {
  const [info, setInfo] = useState<DatasetInfo | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [listError, setListError] = useState<string | null>(null);

  useEffect(() => {
    const ctl = new AbortController();
    setInfo(null);
    setSelected(null);
    setListError(null);
    source.loadDataset(ctl.signal).then(
      (d) => {
        setInfo(d);
        setSelected(d.rackIds[0] ?? null);
      },
      (e: unknown) => !aborted(e) && setListError(message(e, "Could not load the dataset")),
    );
    return () => ctl.abort();
  }, [source]);

  useEffect(() => {
    if (selected === null) return;
    const ctl = new AbortController();
    setLoad({ status: "loading" });
    source.getRackView(selected, ctl.signal).then(
      (res) => {
        if (res.kind === "error") setLoad({ status: "error", message: res.message });
        else setLoad({ status: "ready", view: res });
      },
      (e: unknown) => !aborted(e) && setLoad({ status: "error", message: message(e, "Request failed") }),
    );
    return () => ctl.abort();
  }, [source, selected]);

  return (
    <main className="mx-auto max-w-4xl space-y-4 p-4" data-testid="dataset-telemetry-page">
      <h1 className="text-lg font-semibold text-foreground">Dataset telemetry</h1>

      <div role="note" className="rounded-md border border-border p-3 text-xs text-muted-foreground space-y-1" data-testid="dataset-banner">
        <p>
          <strong className="text-foreground">Recorded dataset, source time, timezone not established.</strong> These are historical records, not live
          measurements, and are separate from the simulated facility and its 36 simulated racks.
        </p>
        {source.kind === "fixture" && <p data-testid="fixture-banner">Showing {source.label}. No dataset source is connected.</p>}
        {info?.window && (info.window.first || info.window.last) && (
          <p data-testid="dataset-window">
            Dataset window (source time): {info.window.first ?? "unknown"} to {info.window.last ?? "unknown"}
          </p>
        )}
        {info?.attributionText && <p data-testid="attribution">{info.attributionText}</p>}
        {info?.modificationsStatement && <p data-testid="modifications">{info.modificationsStatement}</p>}
      </div>

      {listError && (
        <p role="alert" className="text-sm text-muted-foreground">
          {listError}
        </p>
      )}

      {info && (
        <div role="group" aria-label="Source rack" className="flex flex-wrap gap-2">
          {info.rackIds.map((id) => (
            <button
              key={id}
              type="button"
              aria-pressed={selected === id}
              onClick={() => setSelected(id)}
              className="rounded-md border border-border px-3 py-1 text-sm aria-pressed:bg-muted aria-pressed:font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Rack {id}
            </button>
          ))}
        </div>
      )}

      <div aria-live="polite">
        {load.status === "loading" && selected !== null && <p className="text-sm text-muted-foreground">Loading rack {selected}…</p>}
        {load.status === "error" && <p className="text-sm text-muted-foreground">Rack readout unavailable: {load.message}</p>}
        {load.status === "ready" && <RackReadout view={load.view} />}
      </div>
    </main>
  );
}
