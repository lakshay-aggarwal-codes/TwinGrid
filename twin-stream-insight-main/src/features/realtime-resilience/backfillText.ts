import type { BackfillState } from './backfill';

export interface BackfillLine {
  /** `data-state` value and a non-colour cue for tests and styling. */
  state: BackfillState['status'];
  text: string;
}

/** One short line for the status bar, or null while there is nothing to say. Counts are as received; a shortfall is stated. */
export function backfillLine(s: BackfillState): BackfillLine | null {
  switch (s.status) {
    case 'idle':
      return null;
    case 'loading':
      return { state: 'loading', text: `Backfilling ${s.window.missedFrames} missed updates…` };
    case 'unavailable':
      return { state: 'unavailable', text: `${s.window.missedFrames} updates missed; stored history unavailable` };
    case 'done': {
      const { recovered, window: w, moreAvailable } = s;
      const base =
        recovered >= w.missedFrames
          ? `Backfilled ${w.missedFrames} missed updates from stored history`
          : `Backfilled ${recovered} of ${w.missedFrames} missed updates (the rest were not stored)`;
      const notes = [w.truncated ? 'oldest part of the gap not requested' : '', moreAvailable ? 'more stored data exists than was loaded' : '']
        .filter(Boolean)
        .join('; ');
      return { state: 'done', text: notes ? `${base}; ${notes}` : base };
    }
  }
}
