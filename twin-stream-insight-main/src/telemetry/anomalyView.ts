/**
 * FE-07: pure presentation mapping for the server-owned anomaly pipeline state (`anomaly_status`, BC-01/BC-07).
 *
 * The browser scores nothing. This module only turns what the backend said into text, an icon id and
 * geometry. Rules it enforces:
 *  - a number is shown ONLY for a scored state (`ok` / `anomalous`) whose `score` was reported; never 0 for the rest;
 *  - the label never says "%", and score is shown beside the BACKEND `threshold`, which is never invented;
 *  - only backend `status === 'anomalous'` raises the banner / flash (`flagged`);
 *  - unknown status text -> "Unrecognised detector status"; a missing status -> "not reported", never "normal";
 *  - the detector is "experimental, trained on simulator data" whenever the backend's `trained_on` says so.
 */
import { AlertTriangle, CheckCircle2, CircleDashed, HelpCircle, Hourglass, ServerCrash, XOctagon, type LucideIcon } from 'lucide-react';
import type { AnomalyStatusPayload } from '../api/apiClient.tsx';

export type AnomalyKind = 'warming_up' | 'ok' | 'anomalous' | 'unavailable' | 'error' | 'unrecognised' | 'not_reported';

/** Distinct icon id per kind (shape, not colour). Mapped to a lucide icon by the component. */
export type AnomalyIcon = 'warming' | 'ok' | 'anomalous' | 'unavailable' | 'error' | 'unrecognised' | 'not_reported';

export interface AnomalyProvenance {
  /** "Origin: Simulated" / "Origin: Unverified source" ... */
  originText: string;
  modelVersionText: string;
  /** "Experimental — trained on simulator data" when the backend says `synthetic`. */
  trainedOnText: string;
  experimental: boolean;
}

export interface AnomalyEpisode {
  open: boolean;
  /** Only backend-supplied values. */
  severity: string | null;
  alertId: number | null;
}

export interface AnomalyView {
  kind: AnomalyKind;
  icon: AnomalyIcon;
  label: string;
  /** One fixed sentence per kind (the backend `message` is not shown for fail-closed states). */
  explanation: string;
  /** Raised only for backend `anomalous`. Drives banner, flash and the one-time announcement. */
  flagged: boolean;
  /** Present only for scored kinds with a reported score. */
  score?: number;
  /** Present only when the backend reported a threshold for a scored kind. */
  threshold?: number;
  /** "score 0.0123 / threshold 0.0100" | "score 0.0123 (threshold not reported)" | undefined (no number at all). */
  readout?: string;
  warmup?: { filled: number; window: number };
  /** Backend detector type and message, shown only for `anomalous`. */
  type?: string;
  message?: string;
  episode?: AnomalyEpisode;
  provenance: AnomalyProvenance;
  /** Screen-reader text; equals the visual state (label + readout + provenance). */
  srText: string;
}

/** Distinct icon shape per kind; the component only renders it (decorative: the label carries the meaning). */
export const ANOMALY_ICONS: Record<AnomalyIcon, LucideIcon> = {
  warming: Hourglass,
  ok: CheckCircle2,
  anomalous: AlertTriangle,
  unavailable: ServerCrash,
  error: XOctagon,
  unrecognised: HelpCircle,
  not_reported: CircleDashed,
};

const NOT_REPORTED = 'not reported';

export function formatDetectorNumber(x: number): string {
  if (x === 0) return '0.0000';
  return Math.abs(x) >= 0.0001 ? x.toFixed(4) : x.toExponential(2);
}

function finite(x: unknown): x is number {
  return typeof x === 'number' && Number.isFinite(x);
}

function originText(origin: unknown): string {
  if (origin === 'simulated') return 'Origin: Simulated';
  if (origin === 'measured') return 'Origin: Measured';
  if (origin === 'replayed') return 'Origin: Replayed (not live)';
  return 'Origin: Unverified source'; // absent, null or unrecognised
}

function provenanceOf(a: AnomalyStatusPayload | null): AnomalyProvenance {
  const trainedOn = a?.trained_on;
  const synthetic = trainedOn === 'synthetic';
  const model = a?.model_version;
  return {
    originText: originText(a?.origin),
    modelVersionText: typeof model === 'string' && model !== '' ? `Model version: ${model}` : `Model version: ${NOT_REPORTED}`,
    trainedOnText: synthetic
      ? 'Experimental — trained on simulator data'
      : typeof trainedOn === 'string' && trainedOn !== ''
        ? `Trained on: ${trainedOn}`
        : `Training data: ${NOT_REPORTED}`,
    experimental: synthetic,
  };
}

const EXPLANATION: Record<AnomalyKind, string> = {
  warming_up: 'The detector is collecting its first window of samples. No score yet.',
  ok: 'The detector scored the latest window below its own threshold.',
  anomalous: 'The detector scored the latest window above its own threshold.',
  unavailable: 'The detector is not producing scores. No anomaly assessment is available.',
  error: 'The detector reported an error. No anomaly assessment is available.',
  unrecognised: 'The backend reported a detector status this app does not recognise. No assessment is shown.',
  not_reported: 'No detector status has been received. No anomaly assessment is available.',
};

const LABEL: Record<Exclude<AnomalyKind, 'warming_up'>, string> = {
  ok: 'No anomaly flagged',
  anomalous: 'Anomaly flagged',
  unavailable: 'Detector unavailable',
  error: 'Detector error',
  unrecognised: 'Unrecognised detector status',
  not_reported: 'Detector status not reported',
};

const ICON: Record<AnomalyKind, AnomalyIcon> = {
  warming_up: 'warming',
  ok: 'ok',
  anomalous: 'anomalous',
  unavailable: 'unavailable',
  error: 'error',
  unrecognised: 'unrecognised',
  not_reported: 'not_reported',
};

function kindOf(a: AnomalyStatusPayload | null | undefined): AnomalyKind {
  if (!a) return 'not_reported';
  switch (a.status) {
    case 'warming_up':
      return 'warming_up';
    case 'ok':
      return 'ok';
    case 'anomalous':
      return 'anomalous';
    case 'unavailable':
      return 'unavailable';
    case 'error':
      return 'error';
    default:
      return 'unrecognised';
  }
}

export function toAnomalyView(a: AnomalyStatusPayload | null | undefined): AnomalyView {
  const kind = kindOf(a);
  const provenance = provenanceOf(a ?? null);
  const scored = kind === 'ok' || kind === 'anomalous';

  const view: AnomalyView = {
    kind,
    icon: ICON[kind],
    label: '',
    explanation: EXPLANATION[kind],
    flagged: kind === 'anomalous',
    provenance,
    srText: '',
  };

  if (kind === 'warming_up') {
    const filled = a?.window_filled;
    const window = a?.window_size;
    if (finite(filled) && finite(window)) {
      view.warmup = { filled, window };
      view.label = `Warming up (${filled}/${window})`;
    } else {
      view.label = 'Warming up (progress not reported)';
    }
  } else {
    view.label = LABEL[kind];
  }

  if (scored && a) {
    if (finite(a.score)) {
      view.score = a.score;
      if (finite(a.threshold)) {
        view.threshold = a.threshold;
        view.readout = `score ${formatDetectorNumber(a.score)} / threshold ${formatDetectorNumber(a.threshold)}`;
      } else {
        view.readout = `score ${formatDetectorNumber(a.score)} (threshold ${NOT_REPORTED})`;
      }
    } else {
      view.readout = `score ${NOT_REPORTED}`;
    }
  }

  if (kind === 'anomalous' && a) {
    if (typeof a.type === 'string' && a.type !== '') view.type = a.type;
    if (typeof a.message === 'string' && a.message !== '') view.message = a.message;
  }

  if (a?.episode && typeof a.episode.open === 'boolean') {
    view.episode = {
      open: a.episode.open,
      severity: a.episode.severity ?? null,
      alertId: a.episode.alert_id ?? null,
    };
  }

  const parts = [view.label];
  if (view.readout) parts.push(view.readout);
  parts.push(provenance.trainedOnText, provenance.modelVersionText, provenance.originText);
  view.srText = parts.join('. ');
  return view;
}

export interface GaugeGeometry {
  /** 0..1 of the arc that is filled. */
  fillFraction: number;
  /** 0..1 position of the threshold marker. Fixed: the threshold is the arc's midpoint. */
  markerFraction: number;
  /** score is beyond the arc's range (more than twice the threshold). */
  overflow: boolean;
}

/**
 * Purely geometric: the arc spans 0 .. 2x the backend threshold, so the marker sits at the midpoint.
 * This is a drawing aid; no label derived from it (never "%", never a rescaled score). Returns null unless a
 * scored view has BOTH a score and a positive backend threshold (nothing is fabricated).
 */
export function gaugeGeometry(view: AnomalyView): GaugeGeometry | null {
  if (view.kind !== 'ok' && view.kind !== 'anomalous') return null;
  if (!finite(view.score) || !finite(view.threshold) || view.threshold <= 0) return null;
  const ratio = Math.max(0, view.score) / view.threshold;
  return { fillFraction: Math.min(ratio / 2, 1), markerFraction: 0.5, overflow: ratio > 2 };
}
