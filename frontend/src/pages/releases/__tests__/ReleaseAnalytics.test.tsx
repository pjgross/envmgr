import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import ReleaseAnalytics from '../ReleaseAnalytics';

// The page fetches scope-churn (existing) + release-metrics + conflicts (new).
// Mock all three services so no HTTP is made.
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
      success_rate: 0.75,
      shipped_count: 4,
      failed_count: 1,
      emergency_pct: 0.25,
      emergency_count: 1,
      closed_count: 4,
      avg_cycle_time_seconds: 3 * 86400,
      cycle_time_count: 4,
    }),
    conflicts: vi.fn().mockResolvedValue([
      { environment_id: 1, environment_name: 'SIT', month: '2026-06', conflict_count: 2 },
    ]),
  },
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <ReleaseAnalytics />
    </MemoryRouter>,
  );
}

describe('ReleaseAnalytics release-metrics section', () => {
  it('renders the success-rate card value', async () => {
    renderPage();
    expect(await screen.findByText('75.0%')).toBeInTheDocument();
  });

  it('renders the emergency-% card value', async () => {
    renderPage();
    expect(await screen.findByText('25.0%')).toBeInTheDocument();
  });

  it('renders the average cycle-time card value', async () => {
    renderPage();
    expect(await screen.findByText('3d')).toBeInTheDocument();
  });

  it('renders a booking-conflict row naming the environment', async () => {
    renderPage();
    expect(await screen.findByText('SIT')).toBeInTheDocument();
  });
});
