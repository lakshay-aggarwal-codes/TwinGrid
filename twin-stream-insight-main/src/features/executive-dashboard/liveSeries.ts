import type { LiveStatePayload } from "@/api/apiClient";

/**
 * Task 16: a bounded, in-memory record of the live frames this browser tab has received. The backend stores no PUE or
 * total-power history (only five sensor measurands), so any trend of those values can only be "since this page was
 * receiving frames", and every statement built on it says so. Pure: no React, no clock, no network.
 */

export interface LiveSample {
  /** Browser wall clock (epoch ms) when the frame was accepted. */
  readonly t: number;
  readonly seq: number | null;
  readonly pue: number;
  readonly itKw: number;
  readonly coolingKw: number;
  readonly totalKw: number;
  readonly outletC: number;
  readonly carbonGPerKwh: number | null;
  readonly carbonReal: boolean | null;
}

/** 1800 samples = 90 min at the backend's 3 s tick. */
export const MAX_SAMPLES = 1800;
/** A pause longer than this ends the contiguous run: the old samples are dropped rather than bridged. */
export const MAX_GAP_MS = 60_000;

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** A frame without a finite PUE, IT power, cooling power or outlet temperature is not recorded (never filled with 0). */
export function sampleFromFrame(state: LiveStatePayload, nowMs: number): LiveSample | null {
  if (!finite(state.pue) || !finite(state.it_power_kw) || !finite(state.cooling_power_kw) || !finite(state.server_outlet_temp_C)) return null;
  return {
    t: nowMs,
    seq: finite(state.seq) ? state.seq : null,
    pue: state.pue,
    itKw: state.it_power_kw,
    coolingKw: state.cooling_power_kw,
    totalKw: finite(state.total_power_kw) ? state.total_power_kw : state.it_power_kw + state.cooling_power_kw,
    outletC: state.server_outlet_temp_C,
    carbonGPerKwh: finite(state.carbon_intensity_gco2_per_kwh) ? state.carbon_intensity_gco2_per_kwh : null,
    carbonReal: typeof state.carbon_data_is_real === "boolean" ? state.carbon_data_is_real : null,
  };
}

/** Returns the same array when the sample is a duplicate or out of order; a new array otherwise. */
export function appendSample(buf: readonly LiveSample[], s: LiveSample): readonly LiveSample[] {
  const last = buf[buf.length - 1];
  if (last) {
    if (last.seq !== null && s.seq !== null && s.seq === last.seq) return buf;
    if (s.t <= last.t) return buf;
    const restarted = last.seq !== null && s.seq !== null && s.seq < last.seq;
    if (restarted || s.t - last.t > MAX_GAP_MS) return [s];
  }
  const next = [...buf, s];
  return next.length > MAX_SAMPLES ? next.slice(next.length - MAX_SAMPLES) : next;
}

/** The samples within `windowMs` of the newest one, oldest first. */
export function windowSamples(buf: readonly LiveSample[], windowMs: number): readonly LiveSample[] {
  const last = buf[buf.length - 1];
  if (!last) return buf;
  const from = last.t - windowMs;
  return buf.filter((s) => s.t >= from);
}
