import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import DeploymentStatusChip from '../DeploymentStatusChip';

describe('DeploymentStatusChip', () => {
  it.each([
    ['pending', 'Pending'],
    ['in_progress', 'In progress'],
    ['success', 'Success'],
    ['failed', 'Failed'],
    ['rolled_back', 'Rolled back'],
  ] as const)('renders %s with label %s', (status, label) => {
    render(<DeploymentStatusChip status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
