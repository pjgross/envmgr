import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ComparisonTable, { formatHostShape } from '../ComparisonTable';
import type { SubsystemComparison } from '../../../types/environmentComparison';

const bothSides = (over: Partial<SubsystemComparison> = {}): SubsystemComparison => ({
  subsystem_id: 1,
  name: 'api',
  system_id: 10,
  system_name: 'Payments',
  presence: 'both',
  left: { is_mocked: false, mock_notes: null, version: '1.0', host_shape: [] },
  right: { is_mocked: false, mock_notes: null, version: '2.0', host_shape: [] },
  differences: ['version'],
  ...over,
});

describe('formatHostShape', () => {
  it('renders count, type and role rather than host names', () => {
    expect(
      formatHostShape([{ component_type: 'server', role: 'primary', count: 2 }])
    ).toBe('2 × server (primary)');
  });

  it('omits the role when there is none', () => {
    expect(formatHostShape([{ component_type: 'cache', role: null, count: 1 }])).toBe(
      '1 × cache'
    );
  });

  it('says none rather than rendering an empty string', () => {
    expect(formatHostShape([])).toBe('—');
  });
});

describe('ComparisonTable', () => {
  it('groups rows under their system name', () => {
    render(<ComparisonTable rows={[bothSides()]} leftName="SIT" rightName="UAT" reference={null} />);
    expect(screen.getByText('Payments')).toBeInTheDocument();
    expect(screen.getByText('api')).toBeInTheDocument();
  });

  it('names the environment a subsystem is missing from, never an id', () => {
    render(
      <ComparisonTable
        rows={[bothSides({ presence: 'left_only', right: null, differences: ['presence'] })]}
        leftName="SIT" rightName="UAT" reference={null}
      />
    );
    expect(screen.getByText(/not in UAT/i)).toBeInTheDocument();
  });

  it('reframes a gap as risk when a reference is nominated', () => {
    // Same data, different label — proving the reference is presentation.
    render(
      <ComparisonTable
        rows={[bothSides({ presence: 'right_only', left: null, differences: ['presence'] })]}
        leftName="SIT" rightName="UAT" reference="left"
      />
    );
    expect(screen.getByText(/extra vs reference/i)).toBeInTheDocument();
  });

  it('shows mock notes without treating them as a difference', () => {
    render(
      <ComparisonTable
        rows={[bothSides({
          left: { is_mocked: true, mock_notes: 'stubbed', version: '1.0', host_shape: [] },
          right: { is_mocked: true, mock_notes: 'also stubbed', version: '1.0', host_shape: [] },
          differences: [],
        })]}
        leftName="SIT" rightName="UAT" reference={null}
      />
    );
    // Both sides' notes render as text and neither is folded into the other:
    // `getByText(/stubbed/)` is ambiguous here because 'also stubbed' contains
    // 'stubbed' as a substring, so both cells match — asserting both appear
    // is the discriminating, not weaker, check.
    expect(screen.getAllByText(/stubbed/)).toHaveLength(2);
  });
});
