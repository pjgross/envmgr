import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import ReleaseAnalytics from '../ReleaseAnalytics';

vi.mock('../../../services/releaseService', () => ({
  releaseService: {
    getScopeChurnAnalytics: vi.fn().mockResolvedValue({
      scope_changed: { count: 0, delayed_count: 0, delayed_pct: 0, issue_count: 0, issue_pct: 0 },
      stable: { count: 0, delayed_count: 0, delayed_pct: 0, issue_count: 0, issue_pct: 0 },
      releases: [],
    }),
  },
}));

vi.mock('../../../services/releaseMetricsService', () => ({
  releaseMetricsService: {
    releases: vi.fn().mockResolvedValue({
      success_rate: 0, shipped_count: 0, failed_count: 0, emergency_pct: 0,
      emergency_count: 0, closed_count: 0, avg_cycle_time_seconds: 0, cycle_time_count: 0,
    }),
    conflicts: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock('../../../services/environmentOperatingHoursService', () => ({
  environmentOperatingHoursService: {
    overview: vi.fn().mockResolvedValue({
      rows: [{
        environment_id: 1, environment_name: 'Mortgage SIT', configured: true, timezone: 'UTC',
        total_operating_seconds: 100 * 3600, booked_operating_seconds: 60 * 3600, utilization_ratio: 0.6,
      }],
      unconfigured_count: 2,
    }),
  },
}));

describe('ReleaseAnalytics environment utilization', () => {
  it('renders a utilization row with the environment name', async () => {
    render(<MemoryRouter><ReleaseAnalytics /></MemoryRouter>);
    expect(await screen.findByText('Mortgage SIT')).toBeInTheDocument();
  });

  it('shows the unconfigured-environments caption', async () => {
    render(<MemoryRouter><ReleaseAnalytics /></MemoryRouter>);
    expect(await screen.findByText(/2 environment/i)).toBeInTheDocument();
  });
});
