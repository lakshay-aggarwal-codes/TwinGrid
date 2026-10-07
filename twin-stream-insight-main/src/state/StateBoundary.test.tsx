import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { StateBoundary, StateNotice } from './StateBoundary';
import { expectState } from './testing';
import { STATE_COPY, ERROR_COPY, STALE_REFRESH_FAILED_LABEL } from './errorCopy';
import type { DataState, UiStateKind } from './dataState';

const ALL: UiStateKind[] = [
  'loading',
  'empty',
  'not_run',
  'error',
  'unauthorized',
  'stale',
  'disconnected',
  'unavailable',
  'incomplete',
  'unsupported_scenario',
  'unavailable_model',
];

describe('StateNotice: every vocabulary state renders text + icon + role', () => {
  it.each(ALL)('%s', (kind) => {
    render(<StateNotice kind={kind} />);
    expectState(kind, { text: STATE_COPY[kind].title });
    expectState(kind, { text: STATE_COPY[kind].description });
  });

  it('disconnected is announced assertively; no other state sets aria-live', () => {
    const { container, rerender } = render(<StateNotice kind="disconnected" />);
    expect(container.querySelector('[data-state="disconnected"]')).toHaveAttribute('aria-live', 'assertive');
    rerender(<StateNotice kind="stale" />);
    expect(container.querySelector('[data-state="stale"]')).not.toHaveAttribute('aria-live');
  });

  it('empty, not_run and unavailable never render a bare "0"', () => {
    for (const kind of ['empty', 'not_run', 'unavailable'] as const) {
      const { container, unmount } = render(<StateNotice kind={kind} />);
      expect(container.textContent?.trim()).not.toBe('0');
      unmount();
    }
  });
});

describe('StateBoundary', () => {
  const retry = vi.fn();
  const renderState = (state: DataState<number[]>, extra: { onRetry?: () => void } = {}) =>
    render(<StateBoundary state={state} {...extra}>{(d) => <p>rows:{d.length}</p>}</StateBoundary>);

  it('loading / empty / not_run use their own states', () => {
    for (const status of ['loading', 'empty', 'not_run'] as const) {
      const { unmount } = renderState({ status });
      expectState(status, { text: STATE_COPY[status].description });
      unmount();
    }
  });

  it('feature wording overrides the generic default for loading/empty/not_run', () => {
    render(<StateBoundary state={{ status: 'not_run' }} messages={{ not_run: 'No evaluation has been run.' }}>{() => null}</StateBoundary>);
    expectState('not_run', { text: 'No evaluation has been run.' });
  });

  it('error: copy is selected by kind, and retry is offered only for retryable kinds', () => {
    const { unmount } = renderState({ status: 'error', kind: 'network' }, { onRetry: retry });
    expectState('error', { text: ERROR_COPY.network.description });
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(retry).toHaveBeenCalledTimes(1);
    unmount();

    renderState({ status: 'error', kind: 'validation' }, { onRetry: retry });
    expectState('error', { text: ERROR_COPY.validation.description });
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
  });

  it('unauthorized: sign-in vs no permission, never a retry', () => {
    const { unmount } = renderState({ status: 'unauthorized', reason: 'session_expired' }, { onRetry: retry });
    expectState('unauthorized', { text: /sign in again/i });
    expect(screen.queryByRole('button')).toBeNull();
    unmount();
    renderState({ status: 'unauthorized', reason: 'forbidden' }, { onRetry: retry });
    expectState('unauthorized', { text: /permission/i });
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('contract and unavailable errors render as unavailable (alert), not generic error', () => {
    renderState({ status: 'error', kind: 'contract' });
    expectState('unavailable', { text: ERROR_COPY.contract.description });
  });

  it('503 model_unavailable renders as unavailable_model (status), not error', () => {
    renderState({ status: 'error', kind: 'unavailable', code: 'model_unavailable' });
    expectState('unavailable_model', { text: STATE_COPY.unavailable_model.description });
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('ready renders children; failed refresh shows last-good data with the stale label', () => {
    renderState({ status: 'ready', data: [1, 2, 3] });
    expect(screen.getByText('rows:3')).toBeInTheDocument();
    expect(document.querySelector('[data-state="stale"]')).toBeNull();

    renderState({ status: 'ready', data: [1], freshness: 'stale', refreshFailed: true }, { onRetry: retry });
    expectState('stale', { text: STALE_REFRESH_FAILED_LABEL });
    expect(screen.getByText('rows:1')).toBeInTheDocument();
  });

  it('incomplete fields are listed as not reported, never hidden', () => {
    renderState({ status: 'ready', data: [], incomplete: ['PUE', 'WUE'] });
    expectState('incomplete', { text: 'Not reported: PUE, WUE.' });
  });

  it('no raw message path: backend text smuggled into a state object is never rendered', () => {
    const hostile = { status: 'error', kind: 'server', message: 'SECRET-DETAIL', detail: 'SECRET-DETAIL' } as unknown as DataState<never>;
    const { container } = render(<StateBoundary state={hostile}>{() => null}</StateBoundary>);
    expect(container.textContent).not.toContain('SECRET-DETAIL');
  });
});
