import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import type { Freshness, FreshnessState } from '@/telemetry/freshness';
import { buildProvenance, type ProvenanceInput } from './model';
import { FreshnessChip } from './FreshnessChip';
import { ProvenanceBadge } from './ProvenanceBadge';
import { ProvenanceDetail } from './ProvenanceDetail';
import { ProvenanceStrip } from './ProvenanceStrip';
import { ProvenanceStateMatrix } from './ProvenanceStateMatrix';

// jsdom has no ResizeObserver (Radix Popper needs one). Test-local stub: setup.ts is outside this task's allowance.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

const fresh = (state: FreshnessState, ageMs: number | null = null): Freshness => ({ state, ageMs, staleAfterMs: 9000, lastReceivedAt: null });
const view = (over: Partial<ProvenanceInput> = {}) => buildProvenance({ source: { kind: 'live-feed' }, ...over });

describe('ProvenanceBadge (tier 1)', () => {
  it.each([
    ['simulated', 'Simulated', 'origin-simulated'],
    ['measured', 'Measured', 'origin-measured'],
    ['replayed', 'Replayed (not live)', 'origin-replayed'],
    [undefined, 'Unverified source', 'origin-unverified'],
    ['mystery', 'Unverified source', 'origin-unverified'],
  ])('origin %s -> text "%s" plus a distinct icon shape', (origin, text, icon) => {
    const { container } = render(<ProvenanceBadge view={view({ origin })} />);
    const pill = container.querySelector('[data-origin]')!;
    expect(pill).toHaveTextContent(text);
    const svg = pill.querySelector(`[data-prov-icon="${icon}"]`);
    expect(svg).not.toBeNull();
    expect(svg).toHaveAttribute('aria-hidden', 'true');
  });

  it('is a labelled group, not a live region (no announcement per tick)', () => {
    const { container } = render(<ProvenanceBadge view={view({ origin: 'simulated', freshness: fresh('live', 100) })} />);
    expect(screen.getByRole('group', { name: 'Data provenance' })).toBeInTheDocument();
    expect(container.querySelector('[role="status"],[aria-live]')).toBeNull();
  });

  it('always shows the origin even when every other field is absent (simulated cannot be hidden)', () => {
    render(<ProvenanceBadge view={view({ origin: 'simulated' })} />);
    expect(screen.getByText('Simulated')).toBeVisible();
  });

  it('shows freshness chip text, quality, fallback and preview in the compact tier', () => {
    const v = buildProvenance({
      source: { kind: 'preview' },
      origin: 'simulated',
      quality: 'suspect',
      inputsFallback: ['carbon'],
      freshness: fresh('stale', 42_000),
    });
    const { container } = render(<ProvenanceBadge view={v} />);
    const text = container.textContent ?? '';
    for (const t of ['Simulated', 'Preview', 'Suspect', 'Fallback carbon (flat constant)', 'Stale · last update 42 s ago', 'Simulator-only']) {
      expect(text).toContain(t);
    }
  });

  it('stale / disconnected / reconnecting never render the live text', () => {
    for (const s of ['stale', 'disconnected', 'reconnecting'] as const) {
      const { container, unmount } = render(<ProvenanceBadge view={view({ origin: 'simulated', freshness: fresh(s, 3000) })} />);
      expect(container.querySelector('[data-freshness="live"]')).toBeNull();
      expect(container.querySelector(`[data-freshness="${s}"]`)).not.toBeNull();
      unmount();
    }
  });

  it('each freshness state has its own icon shape', () => {
    const states: FreshnessState[] = ['connecting', 'live', 'stale', 'disconnected', 'reconnecting', 'unavailable'];
    const icons = states.map((s) => {
      const { container, unmount } = render(<FreshnessChip view={view({ freshness: fresh(s, 1000) })} />);
      const icon = container.querySelector('[data-prov-icon]')!.getAttribute('data-prov-icon');
      unmount();
      return icon;
    });
    expect(new Set(icons).size).toBe(states.length);
  });
});

describe('FreshnessChip', () => {
  it('renders nothing without freshness', () => {
    const { container } = render(<FreshnessChip view={view({ origin: 'simulated' })} announce />);
    expect(container).toBeEmptyDOMElement();
  });

  it('announce adds one polite status with the state only (no age); disconnected is assertive', () => {
    const { container, rerender } = render(<FreshnessChip view={view({ freshness: fresh('stale', 42_000) })} announce />);
    const live = container.querySelector('[role="status"]')!;
    expect(live).toHaveAttribute('aria-live', 'polite');
    expect(live).toHaveTextContent(/^Stale$/);
    rerender(<FreshnessChip view={view({ freshness: fresh('disconnected', 120_000) })} announce />);
    expect(container.querySelector('[role="status"]')).toHaveAttribute('aria-live', 'assertive');
    expect(container.querySelector('[role="status"]')).toHaveTextContent(/^Disconnected$/);
  });

  it('without announce there is no live region', () => {
    const { container } = render(<FreshnessChip view={view({ freshness: fresh('stale', 42_000) })} />);
    expect(container.querySelector('[role="status"],[aria-live]')).toBeNull();
  });

  it('the connecting spinner stops under reduced motion', () => {
    const { container } = render(<FreshnessChip view={view({ freshness: fresh('connecting') })} />);
    expect(container.querySelector('[data-prov-icon="fresh-connecting"]')!.getAttribute('class')).toContain('motion-reduce:animate-none');
  });
});

describe('ProvenanceStrip (tier 2)', () => {
  it('shows the context line, scenario and run, preview wording and the details trigger', () => {
    const v = buildProvenance({
      source: { kind: 'preview' },
      origin: 'simulated',
      serverTime: '2026-10-06T14:03:21Z',
      simTime: '2026-01-01T12:35:00',
      scenarioId: 'scn-7',
      runId: 'run-2',
      weatherSource: 'reference',
      plantKind: 'simulated',
    });
    const { container } = render(<ProvenanceStrip view={v} />);
    expect(container.querySelector('[data-provenance-line]')).toHaveTextContent('Preview · server time 14:03:21 UTC · simulated clock 2026-01-01 12:35');
    expect(container.querySelector('[data-provenance-scenario]')).toHaveTextContent('Scenario scn-7');
    expect(container.querySelector('[data-provenance-run]')).toHaveTextContent('Run run-2');
    expect(container.querySelector('[data-provenance-preview]')).toHaveTextContent('Preview — what this configuration would produce');
    expect(container.textContent).toContain('Reference weather, simulated plant');
    expect(screen.getByRole('button', { name: 'Provenance details' })).toBeInTheDocument();
  });

  it('omits scenario/run when not provided and never invents them', () => {
    const { container } = render(<ProvenanceStrip view={view({ origin: 'simulated' })} />);
    expect(container.querySelector('[data-provenance-scenario]')).toBeNull();
    expect(container.querySelector('[data-provenance-run]')).toBeNull();
  });

  it('renders children (e.g. preview inputs) inside the strip', () => {
    render(
      <ProvenanceStrip view={view({ origin: 'simulated' })}>
        <span>inputs here</span>
      </ProvenanceStrip>,
    );
    expect(screen.getByText('inputs here')).toBeInTheDocument();
  });
});

describe('ProvenanceDetail (tier 3)', () => {
  it('inline: lists every row, with "not reported" for missing fields', () => {
    const v = view({ origin: 'simulated', physicsVersion: '1.2.0' });
    const { container } = render(<ProvenanceDetail view={v} inline />);
    const rows = container.querySelectorAll('[data-detail-row]');
    expect(rows).toHaveLength(18);
    const phys = container.querySelector('[data-detail-row="physics"]')!;
    expect(phys).toHaveTextContent('Physics version');
    expect(phys).toHaveTextContent('1.2.0');
    expect(phys.getAttribute('data-reported')).toBe('true');
    const model = container.querySelector('[data-detail-row="model"]')!;
    expect(model).toHaveTextContent('not reported');
    expect(model.getAttribute('data-reported')).toBe('false');
  });

  it('uses a description list with a labelled region (structure for assistive tech)', () => {
    const { container } = render(<ProvenanceDetail view={view({ origin: 'simulated' })} inline />);
    expect(screen.getByRole('region', { name: 'Provenance details' })).toBeInTheDocument();
    expect(container.querySelectorAll('dt')).toHaveLength(18);
    expect(container.querySelectorAll('dd')).toHaveLength(18);
  });

  it('popover: keyboard-operable trigger opens a labelled dialog that lists the three distinct clocks; Escape closes it', () => {
    const v = view({ origin: 'simulated', serverTime: '2026-10-06T14:03:21Z', simTime: '2026-01-01T12:35:00', freshness: fresh('stale', 42_000) });
    render(<ProvenanceDetail view={v} />);
    const trigger = screen.getByRole('button', { name: 'Provenance details' });
    expect(trigger.tagName).toBe('BUTTON');
    expect(trigger).toHaveAttribute('type', 'button');
    fireEvent.click(trigger);
    const dialog = screen.getByRole('dialog', { name: 'Provenance details' });
    const w = within(dialog);
    expect(w.getByText('Last updated — server time')).toBeInTheDocument();
    expect(w.getByText('Last updated — simulated clock')).toBeInTheDocument();
    expect(w.getByText('Last received — browser receipt age')).toBeInTheDocument();
    expect(w.getByText('2026-10-06 14:03:21 UTC')).toBeInTheDocument();
    expect(w.getByText('42 s ago')).toBeInTheDocument();
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('no row is blank or a bare zero', () => {
    const { container } = render(<ProvenanceDetail view={buildProvenance({ source: { kind: null } })} inline />);
    container.querySelectorAll('dd').forEach((dd) => {
      expect((dd.textContent ?? '').trim()).not.toBe('');
      expect((dd.textContent ?? '').trim()).not.toBe('0');
    });
  });
});

describe('state matrix (evidence artifact)', () => {
  it('renders every state through the view-model; measured appears only for the backend-measured row', () => {
    const { container } = render(<ProvenanceStateMatrix />);
    const measured = container.querySelectorAll('[data-origin="measured"]');
    expect(measured).toHaveLength(1);
    for (const o of ['simulated', 'replayed', 'unverified']) expect(container.querySelector(`[data-origin="${o}"]`)).not.toBeNull();
    for (const f of ['live', 'stale', 'disconnected', 'reconnecting', 'connecting', 'unavailable']) {
      expect(container.querySelector(`[data-freshness="${f}"]`)).not.toBeNull();
    }
  });
});
