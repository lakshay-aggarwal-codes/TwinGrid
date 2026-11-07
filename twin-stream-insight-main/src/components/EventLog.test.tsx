import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EventLog } from './EventLog';

describe('EventLog', () => {
  it('says there are no events yet instead of showing an empty box', () => {
    render(<EventLog events={[]} />);
    expect(screen.getByTestId('event-log-empty')).toHaveTextContent('No events yet');
  });

  it('lists events and drops the empty message once there is one', () => {
    render(<EventLog events={[{ id: 1, type: 'success', message: '24h simulation finished', time: '12:00:00' }]} />);
    expect(screen.getByText('24h simulation finished')).toBeInTheDocument();
    expect(screen.queryByTestId('event-log-empty')).toBeNull();
  });
});
