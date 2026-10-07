import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Route, Routes, Link } from 'react-router-dom';
import { AppErrorBoundary, RouteErrorBoundary } from './AppErrorBoundary';
import { RENDER_ERROR_COPY } from './errorCopy';

vi.mock('@/lib/errorReporter', () => ({ reportError: vi.fn() }));
import { reportError } from '@/lib/errorReporter';

function Boom({ message = 'SECRET render failure' }: { message?: string }): never {
  throw new Error(message);
}

describe('AppErrorBoundary', () => {
  beforeEach(() => {
    vi.mocked(reportError).mockClear();
    vi.spyOn(console, 'error').mockImplementation(() => {}); // React logs caught render errors
  });
  afterEach(() => vi.restoreAllMocks());

  it('catches a thrown render, reports it, and shows generic copy in an alert', () => {
    render(
      <AppErrorBoundary scope="app">
        <Boom />
      </AppErrorBoundary>,
    );
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(RENDER_ERROR_COPY.title);
    expect(alert).toHaveTextContent(RENDER_ERROR_COPY.description);
    expect(reportError).toHaveBeenCalledWith('AppErrorBoundary:app', expect.objectContaining({ message: 'SECRET render failure' }));
  });

  it('never puts the thrown message in the DOM', () => {
    const { container } = render(
      <AppErrorBoundary scope="app">
        <Boom />
      </AppErrorBoundary>,
    );
    expect(container.textContent).not.toContain('SECRET');
  });

  it('recovery="retry" re-renders the subtree', () => {
    let fail = true;
    function Flaky() {
      if (fail) throw new Error('x');
      return <p>recovered</p>;
    }
    render(
      <AppErrorBoundary scope="r" recovery="retry">
        <Flaky />
      </AppErrorBoundary>,
    );
    fail = false;
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(screen.getByText('recovered')).toBeInTheDocument();
  });

  it('a route boundary clears when the route changes and leaves the shell up', () => {
    render(
      <MemoryRouter initialEntries={['/bad']}>
        <nav>
          <Link to="/good">go good</Link>
        </nav>
        <RouteErrorBoundary>
          <Routes>
            <Route path="/bad" element={<Boom />} />
            <Route path="/good" element={<p>good page</p>} />
          </Routes>
        </RouteErrorBoundary>
      </MemoryRouter>,
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(reportError).toHaveBeenCalledWith('AppErrorBoundary:route:/bad', expect.anything());
    fireEvent.click(screen.getByRole('link', { name: 'go good' }));
    expect(screen.getByText('good page')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
