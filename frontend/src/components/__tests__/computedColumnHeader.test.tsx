import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import ComputedColumnHeader from '../ComputedColumnHeader';

describe('ComputedColumnHeader', () => {
  it('renders the label', () => {
    render(<ComputedColumnHeader label="Phases" />);
    expect(screen.getByText('Phases')).toBeInTheDocument();
  });

  it('explains why the column cannot be sorted', async () => {
    render(<ComputedColumnHeader label="Phases" />);
    await userEvent.hover(screen.getByText('Phases'));
    expect(
      await screen.findByText(/not sortable across all results/i)
    ).toBeInTheDocument();
  });
});
