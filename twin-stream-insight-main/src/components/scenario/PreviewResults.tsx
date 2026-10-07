import { StatusMessage } from '@/components/shell/StatusMessage';
import { PreviewNotice } from '@/components/scenario/ScenarioSliders.tsx';
import type { StateResponse } from '@/api/apiClient';
import { inputsOf, WHATIF_METRICS, type UseWhatIf, type WhatIfResult } from '@/hooks/useWhatIf';
import { ERROR_COPY, STALE_REFRESH_FAILED_LABEL, UNAUTHORIZED_COPY } from '@/state/errorCopy';

/** The live reading shown beside a preview, only for metrics the live state really reports. */
const LIVE_PICK: Record<string, ((s: StateResponse) => number) | undefined> = {
  pue: (s) => s.pue,
  wue: (s) => s.wue,
  outlet: (s) => s.server_outlet_temp_C,
};

interface Props {
  a: UseWhatIf;
  b: UseWhatIf;
  /** Real live facility state: an explicitly separate "Live now" column. */
  liveState?: StateResponse | null;
  compact?: boolean;
}

const readyOf = (r: WhatIfResult) => (r.status === 'ready' ? r : null);

function Failure({ result, label }: { result: WhatIfResult; label: string }) {
  if (result.status === 'unauthorized') {
    const copy = result.reason === 'forbidden' ? UNAUTHORIZED_COPY.forbidden : UNAUTHORIZED_COPY.session_expired;
    return (
      <StatusMessage kind="unauthorized" title={`${label}: ${copy.title}`}>
        {copy.description}
      </StatusMessage>
    );
  }
  if (result.status === 'error') {
    const copy = ERROR_COPY[result.kind];
    return (
      <StatusMessage kind="error" title={`${label}: ${copy.title}`}>
        {copy.description}
      </StatusMessage>
    );
  }
  return null;
}

/**
 * Two constant-input previews side by side. A renderer only: every number is a backend field, nothing is ranked,
 * coloured by outcome or compared, and a missing value is shown as not available (never 0).
 */
export function PreviewResults({ a, b, liveState = null, compact = false }: Props) {
  const ra = readyOf(a.result);
  const rb = readyOf(b.result);
  const loading = a.result.status === 'loading' || b.result.status === 'loading';
  const updating = (ra?.updating ?? false) || (rb?.updating ?? false) || a.isFetching || b.isFetching;
  const refreshFailed = (ra?.refreshFailed ?? false) || (rb?.refreshFailed ?? false);
  const fallbackCarbon = (ra !== null && !ra.data.carbon_data_is_real) || (rb !== null && !rb.data.carbon_data_is_real);
  const showLive = liveState !== null;
  const cell = compact ? 'px-2 py-1.5' : 'px-4 py-2.5';
  const head = compact ? 'px-2 py-2 text-[11px]' : 'px-4 py-3 text-xs uppercase tracking-wider';
  const NA = (
    <span title="Not available">
      <span aria-hidden="true">—</span>
      <span className="sr-only">not available</span>
    </span>
  );

  return (
    <div className="space-y-3" data-testid="preview-results">
      <Failure result={a.result} label="Scenario A" />
      <Failure result={b.result} label="Scenario B" />
      {refreshFailed && <StatusMessage kind="stale">{STALE_REFRESH_FAILED_LABEL}</StatusMessage>}
      {loading && <StatusMessage kind="loading">Running preview…</StatusMessage>}
      {!loading && updating && <StatusMessage kind="loading">Updating preview…</StatusMessage>}

      <div className={`rounded-md border border-border overflow-x-auto ${updating ? 'opacity-70' : ''}`}>
        <table className={`w-full ${compact ? 'text-[11px]' : 'text-sm'}`}>
          <caption className="sr-only">Preview results for scenario A and scenario B (simulated, constant inputs)</caption>
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className={`text-left font-medium text-muted-foreground ${head}`}>Metric</th>
              {showLive && <th scope="col" className={`text-right font-medium text-muted-foreground ${head}`}>Live now</th>}
              <th scope="col" className={`text-right font-medium text-muted-foreground ${head}`}>Scenario A</th>
              <th scope="col" className={`text-right font-medium text-muted-foreground ${head}`}>Scenario B</th>
            </tr>
          </thead>
          <tbody>
            {WHATIF_METRICS.map((m) => {
              const livePick = LIVE_PICK[m.key];
              const live = showLive && livePick ? livePick(liveState as StateResponse) : null;
              return (
                <tr key={m.key} className="border-b border-border/50">
                  <th scope="row" className={`text-left font-normal text-muted-foreground ${cell}`}>{m.label}</th>
                  {showLive && <td className={`text-right font-mono text-muted-foreground ${cell}`}>{live === null || live === undefined ? NA : m.format(live)}</td>}
                  <td className={`text-right font-mono ${cell}`}>{ra ? m.format(m.pick(ra.data)) : NA}</td>
                  <td className={`text-right font-mono ${cell}`}>{rb ? m.format(m.pick(rb.data)) : NA}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {fallbackCarbon && (
        <p className="text-[11px] text-muted-foreground" data-testid="fallback-carbon">
          CO₂ uses a fallback carbon intensity (a flat constant); the backend reports it is not real grid data.
        </p>
      )}

      {ra && <PreviewNotice data={ra.data} inputs={inputsOf(ra.data, ra.params)} />}
      {rb && <PreviewNotice data={rb.data} inputs={inputsOf(rb.data, rb.params)} />}
    </div>
  );
}
