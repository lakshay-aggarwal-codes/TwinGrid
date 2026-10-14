/** Task 14: SVG path for one replay series. PURE. No smoothing, no interpolation, no downsampling: one vertex per stored sample, and the line is broken at every backend-reported gap. */
import type { ReplaySeries } from "./dataset";

export interface Box {
  readonly width: number;
  readonly height: number;
  readonly fromMs: number;
  readonly toMs: number;
}

/** Min/max of the stored values. A flat series gets +-1 so it is drawn mid-height, not stretched. Null when there is nothing to draw. */
export function valueDomain(s: ReplaySeries): { min: number; max: number } | null {
  if (s.values.length === 0) return null;
  let min = Infinity;
  let max = -Infinity;
  for (const v of s.values) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  return min === max ? { min: min - 1, max: max + 1 } : { min, max };
}

const num = (n: number) => String(Math.round(n * 100) / 100);

export function xFor(ms: number, box: Box): number {
  return box.toMs <= box.fromMs ? 0 : ((ms - box.fromMs) / (box.toMs - box.fromMs)) * box.width;
}

export function yFor(v: number, domain: { min: number; max: number }, box: Box): number {
  return box.height - ((v - domain.min) / (domain.max - domain.min)) * box.height;
}

/** `M x,y L x,y ...` per segment ("" for no data). A segment of one sample is a zero-length line so the point is still visible with a round cap. */
export function buildPath(s: ReplaySeries, box: Box, domain: { min: number; max: number }): string {
  const parts: string[] = [];
  let segment: string[] = [];
  const flush = () => {
    if (segment.length === 0) return;
    parts.push(segment.length === 1 ? `${segment[0]} L${segment[0].slice(1)}` : segment.join(" L"));
    segment = [];
  };
  let prev: number | null = null;
  for (let i = 0; i < s.times.length; i += 1) {
    const t = s.times[i];
    if (t < box.fromMs || t > box.toMs) continue;
    const before = prev;
    if (before !== null && s.gaps.some((g) => g.x1 >= before && g.x2 <= t)) flush();
    const pt = `${segment.length === 0 ? "M" : ""}${num(xFor(t, box))},${num(yFor(s.values[i], domain, box))}`;
    segment.push(pt);
    prev = t;
  }
  flush();
  return parts.join(" ");
}
