import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CustomParameters } from './CustomParameters';

describe('CustomParameters', () => {
  it('names the raw sliders honestly and keeps them', () => {
    render(
      <CustomParameters>
        <button>slider stand-in</button>
      </CustomParameters>,
    );
    expect(screen.getByRole('heading', { name: 'Custom parameters (preview)' })).toBeInTheDocument();
    expect(screen.getByText('slider stand-in')).toBeInTheDocument();
    expect(screen.getByText(/no scenario identity/)).toBeInTheDocument();
  });
});
