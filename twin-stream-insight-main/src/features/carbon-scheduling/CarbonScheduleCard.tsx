import { useId, useState } from "react";
import { StateBoundary } from "@/state/StateBoundary";
import { HourStrip } from "./HourStrip";
import {
  DEFAULT_DURATION_H,
  DEFAULT_LOAD_KW,
  ESTIMATE_LABEL,
  MAX_DURATION_H,
  MAX_LOAD_KW,
  formatIntensity,
  formatKg,
  parseDuration,
  parseLoadKw,
  savingWording,
  showsWindow,
  windowLabel,
} from "./model";
import { useCarbonSchedule } from "./useCarbonSchedule";

const FIELD =
  "w-24 rounded-md border border-border bg-background px-2 py-1 font-mono text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-[invalid=true]:border-destructive";

/** Slot `dashboard`: the usual lowest-carbon window for a flexible load, from the hour-of-day carbon curve. */
export default function CarbonScheduleCard() {
  const durId = useId();
  const loadId = useId();
  const demoId = useId();
  const [durText, setDurText] = useState(String(DEFAULT_DURATION_H));
  const [loadText, setLoadText] = useState(String(DEFAULT_LOAD_KW));
  const [synthetic, setSynthetic] = useState(false);
  const dur = parseDuration(durText);
  const load = parseLoadKw(loadText);
  const valid = dur.ok && load.ok;
  const { state, refetch } = useCarbonSchedule(
    { durationH: dur.ok ? dur.value : DEFAULT_DURATION_H, loadKw: load.ok ? load.value : DEFAULT_LOAD_KW, synthetic },
    valid,
  );

  return (
    <section aria-label="Carbon-aware scheduling" data-testid="carbon-card" className="card-grid-glow space-y-2 rounded-lg p-4 md:col-span-2 xl:col-span-1">
      <h2 className="text-xs uppercase tracking-wider text-muted-foreground">Carbon-aware scheduling (flexible load)</h2>

      <div className="flex flex-wrap items-start gap-3">
        <div className="space-y-1">
          <label htmlFor={durId} className="block text-xs text-foreground">Run length (hours, 1–{MAX_DURATION_H})</label>
          <input id={durId} className={FIELD} inputMode="numeric" value={durText} onChange={(e) => setDurText(e.target.value)} aria-invalid={!dur.ok} aria-describedby={dur.ok ? undefined : `${durId}-err`} />
          {dur.ok === false && <p id={`${durId}-err`} role="alert" className="max-w-[14rem] text-[11px] text-destructive-text">{dur.error}</p>}
        </div>
        <div className="space-y-1">
          <label htmlFor={loadId} className="block text-xs text-foreground">Flexible load (kW, up to {MAX_LOAD_KW})</label>
          <input id={loadId} className={FIELD} inputMode="decimal" value={loadText} onChange={(e) => setLoadText(e.target.value)} aria-invalid={!load.ok} aria-describedby={load.ok ? undefined : `${loadId}-err`} />
          {load.ok === false && <p id={`${loadId}-err`} role="alert" className="max-w-[14rem] text-[11px] text-destructive-text">{load.error}</p>}
        </div>
      </div>
      <div className="flex items-start gap-2">
        <input id={demoId} type="checkbox" checked={synthetic} onChange={(e) => setSynthetic(e.target.checked)} className="mt-0.5 h-4 w-4 rounded border-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        <label htmlFor={demoId} className="text-xs text-foreground">
          Show a synthetic demonstration profile <span className="text-muted-foreground">(made-up curve for illustration, not grid data)</span>
        </label>
      </div>

      {!valid ? (
        <p className="text-xs text-muted-foreground" data-testid="carbon-invalid">Fix the highlighted field to see a suggestion.</p>
      ) : (
        <StateBoundary state={state} onRetry={refetch} messages={{ loading: "Looking at the carbon profile…" }}>
          {(c, meta) => {
            const windowShown = showsWindow(c.status) && c.best !== null && c.baseline !== null && c.savings !== null;
            const saving = windowShown && c.savings && c.baseline ? savingWording(c.savings, c.baseline.kind) : null;
            return (
              <div className="space-y-2" aria-busy={meta.refreshFailed || undefined}>
                {c.synthetic_label && (
                  <p data-testid="carbon-synthetic-banner" className="rounded border border-dashed border-foreground px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-foreground">
                    {c.synthetic_label}
                  </p>
                )}
                <p role="status" data-testid="carbon-headline" data-status={c.status} className="text-sm font-medium text-foreground">{c.headline}</p>
                <p className="text-xs text-foreground" data-testid="carbon-message">{c.message}</p>

                {windowShown && c.best && c.baseline && (
                  <>
                    <dl className="grid grid-cols-[1fr_auto] gap-x-3 text-xs" data-testid="carbon-window">
                      <dt className="text-muted-foreground">Window (site-local, {c.site_timezone})</dt>
                      <dd className="font-mono">{windowLabel(c.best.start_hour, c.best.end_hour)}</dd>
                      <dt className="text-muted-foreground">Mean intensity in window</dt>
                      <dd className="font-mono">{formatIntensity(c.best.mean_gco2_per_kwh)}</dd>
                      <dt className="text-muted-foreground">Emissions in window ({c.inputs.load_kw} kW × {c.inputs.duration_h} h)</dt>
                      <dd className="font-mono">{formatKg(c.best.emissions_kg)}</dd>
                    </dl>
                    {saving && <p className="text-xs font-medium text-foreground" data-testid="carbon-saving" data-kind={saving.kind}>{saving.text}</p>}
                    {c.curve_gco2_per_kwh && <HourStrip curve={c.curve_gco2_per_kwh} best={typeof c.best?.start_hour === "number" && typeof c.best?.end_hour === "number" ? { start_hour: c.best.start_hour, end_hour: c.best.end_hour } : null} durationH={c.inputs.duration_h} synthetic={c.status === "synthetic_demo"} />}
                  </>
                )}
                {c.status === "no_variation" && c.curve_gco2_per_kwh && (
                  <p className="font-mono text-xs text-muted-foreground" data-testid="carbon-flat-value">Every hour: {formatIntensity(c.curve_gco2_per_kwh[0])}</p>
                )}
                {c.caveats.map((t) => (
                  <p key={t} className="text-[11px] text-muted-foreground">{t}</p>
                ))}
                <p className="rounded border border-dashed border-border px-2 py-1 text-[11px] text-foreground" data-testid="carbon-label">
                  <strong>{ESTIMATE_LABEL}.</strong> {c.carbon.statement} The load is hypothetical (the value you entered).
                </p>
                <details className="text-[11px] text-muted-foreground">
                  <summary className="cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">How this is computed</summary>
                  <p className="mt-1">{c.basis}</p>
                </details>
              </div>
            );
          }}
        </StateBoundary>
      )}
    </section>
  );
}
