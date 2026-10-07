/** FE-05: icon shape + border-style cue per provenance state. Colour is reinforcement only. */
import {
  AlertTriangle,
  CloudSun,
  Eye,
  FlaskConical,
  Gauge,
  HelpCircle,
  History,
  Loader2,
  Radio,
  RefreshCw,
  ServerOff,
  Clock,
  WifiOff,
  Wrench,
  XOctagon,
  Replace,
  Ban,
  type LucideIcon,
} from 'lucide-react';
import type { ProvenanceIconKey } from './model';

export const ICONS: Record<ProvenanceIconKey, LucideIcon> = {
  'origin-measured': Gauge,
  'origin-simulated': FlaskConical,
  'origin-replayed': History,
  'origin-unverified': HelpCircle,
  preview: Eye,
  weather: CloudSun,
  'simulator-only': Ban,
  'quality-suspect': AlertTriangle,
  'quality-invalid': XOctagon,
  uncalibrated: Wrench,
  fallback: Replace,
  'fresh-connecting': Loader2,
  'fresh-live': Radio,
  'fresh-stale': Clock,
  'fresh-disconnected': WifiOff,
  'fresh-reconnecting': RefreshCw,
  'fresh-unavailable': ServerOff,
};

/** Border style is a second non-colour cue: measured solid+thick, simulated dashed, replayed dotted, unverified double. */
export const ORIGIN_BORDER: Record<string, string> = {
  measured: 'border-2 border-solid border-success text-success-foreground bg-success/20',
  simulated: 'border border-dashed border-primary/70 text-foreground bg-primary/10',
  replayed: 'border border-dotted border-foreground/60 text-foreground bg-muted',
  unverified: 'border-[3px] border-double border-warning text-foreground bg-warning/15',
};

export const TONE: Record<'info' | 'caution' | 'danger', string> = {
  info: 'border border-solid border-border bg-muted text-foreground',
  caution: 'border border-solid border-warning/70 bg-warning/15 text-foreground',
  danger: 'border border-solid border-destructive/70 bg-destructive/10 text-foreground',
};

export const FRESH_STYLE: Record<string, string> = {
  live: 'border border-solid border-border bg-muted text-foreground',
  connecting: 'border border-dotted border-border bg-muted text-muted-foreground',
  stale: 'border-2 border-dashed border-warning bg-warning/15 text-foreground',
  disconnected: 'border-2 border-solid border-destructive/70 bg-destructive/10 text-foreground',
  reconnecting: 'border border-dashed border-warning bg-warning/10 text-foreground',
  unavailable: 'border-2 border-double border-destructive/70 bg-destructive/10 text-foreground',
};
