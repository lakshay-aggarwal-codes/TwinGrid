import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

let demo = true;
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ status: 'signed-in', username: 'Demo visitor', role: 'viewer', notice: null, demo }) }));

import { DemoBanner } from './DemoBanner';

describe('DemoBanner', () => {
  it('shows the persistent "Read-only demo" and "Simulated data" labels in a demo session', () => {
    demo = true;
    render(<DemoBanner />);
    const region = screen.getByRole('region', { name: 'Demo mode' });
    expect(region).toHaveTextContent('Read-only demo');
    expect(region).toHaveTextContent('Simulated data');
  });
  it('shows nothing for a normal session', () => {
    demo = false;
    const { container } = render(<DemoBanner />);
    expect(container).toBeEmptyDOMElement();
  });
});
