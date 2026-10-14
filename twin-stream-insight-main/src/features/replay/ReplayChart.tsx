import { classifyOrigin } from "@/provenance";
import { originForProvenance } from "@/telemetry/history/origin";
import { buildPath, valueDomain, xFor } from "./chartGeometry";
import type { ReadAt, ReplaySeries } from "./dataset";
import { clockUtc, formatReading, fullUtc } from "./format";

const W = 600;
const H = 90;

interface Props {
  series: ReplaySeries;
  fromMs: number;
  toMs: number;
  cursorMs: number | null;
  bMs: number | null;
  read: ReadAt | undefined;
}

/**
 * One stored series over the window. One vertex per stored sample (no smoothing, no downsampling); the line breaks at every
 * backend-reported gap, and the gap is a hatched, labelled band. The cursor is a solid line, compare time B a dashed one.
 */
export function ReplayChart({ series, fromMs, toMs, cursorMs, bMs, read }: Props) {
  const box = { width: W, height: H, fromMs, toMs };
  const domain = valueDomain(series);
  const path = domain ? buildPath(series, box, domain) : "";
  const patternId = `replay-gap-${series.measurand}`;
  const unit = series.unit ?? "(unit not reported)";
  const gaps = series.gaps.filter((g) => g.x2 > fromMs && g.x1 < toMs);
  const origins = series.origins.map((o) => classifyOrigin(originForProvenance(o)).text).join(", ");
  const at =
    read?.kind === "value" ? `${formatReading(series.measurand, read.value)} ${series.unit ?? ""} (sample at ${clockUtc(read.atMs)})` : read?.kind === "gap" ? "no data (stored gap)" : read?.kind === "before-start" ? "no data yet" : cursorMs === null ? "" : "no data";

  return (
    <figure className="space-y-1 rounded-md border border-border bg-card p-3" data-testid={`replay-chart-${series.measurand}`}>
      <figcaption className="flex flex-wrap items-baseline justify-between gap-x-3 text-xs">
        <span className="font-semibold text-foreground">
          {series.label} <span className="font-normal text-muted-foreground">({unit})</span>
        </span>
        <span className="text-muted-foreground" data-testid={`replay-chart-at-${series.measurand}`}>
          {cursorMs === null ? "Live: no cursor" : `${fullUtc(cursorMs)}: ${at}`}
        </span>
      </figcaption>
      {domain === null ? (
        <p className="py-6 text-center text-xs text-muted-foreground">No stored samples in this window.</p>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={`${series.label} over the window, ${series.times.length} stored samples, range ${domain.min} to ${domain.max} ${series.unit ?? ""}`} className="h-24 w-full text-primary">
          <defs>
            <pattern id={patternId} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="6" stroke="currentColor" strokeWidth="1.5" className="text-muted-foreground" />
            </pattern>
          </defs>
          {gaps.map((g) => {
            const x1 = Math.max(0, xFor(g.x1, box));
            const x2 = Math.min(W, xFor(g.x2, box));
            return (
              <g key={`${g.x1}-${g.x2}`} data-testid="replay-gap-band">
                <rect x={x1} y={0} width={Math.max(1, x2 - x1)} height={H} fill={`url(#${patternId})`} opacity="0.5" />
                <title>{`Gap: no stored samples ${fullUtc(g.x1)} to ${fullUtc(g.x2)}`}</title>
              </g>
            );
          })}
          <path d={path} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
          {bMs !== null && <line x1={xFor(bMs, box)} x2={xFor(bMs, box)} y1={0} y2={H} stroke="currentColor" className="text-foreground" strokeWidth="1.5" strokeDasharray="4 3" vectorEffect="non-scaling-stroke" />}
          {cursorMs !== null && <line x1={xFor(cursorMs, box)} x2={xFor(cursorMs, box)} y1={0} y2={H} stroke="currentColor" className="text-foreground" strokeWidth="2" vectorEffect="non-scaling-stroke" />}
        </svg>
      )}
      <p className="text-[11px] text-muted-foreground">
        {domain ? `Range ${domain.min} to ${domain.max}. ` : ""}Origin: {origins || "not reported"}. {series.excluded > 0 ? `${series.excluded} invalid sample(s) not plotted. ` : ""}
        {gaps.length > 0 ? `${gaps.length} gap(s) shown hatched. ` : ""}
        {series.gapsTruncated ? "The backend truncated its gap list. " : ""}
        {series.orderViolations > 0 ? `${series.orderViolations} sample(s) arrived out of order. ` : ""}
        {series.unreadable > 0 ? `${series.unreadable} sample(s) had an unreadable time. ` : ""}
        {series.moreAvailable ? "More stored samples exist than were loaded: choose a shorter window." : ""}
      </p>
    </figure>
  );
}
