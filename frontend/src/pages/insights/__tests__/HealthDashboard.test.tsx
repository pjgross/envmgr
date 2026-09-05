import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import type { EnvironmentHealthOverviewRow } from '../../../types/environmentHealth';
import HealthDashboard from '../HealthDashboard';

// ---------------------------------------------------------------------------
// Mock the service so no HTTP requests are made.
// The factory must be self-contained (vi.mock is hoisted before variable
// declarations, so FIXTURE cannot be referenced from an outer const).
// ---------------------------------------------------------------------------

import { environmentHealthService } from '../../../services/environmentHealthService';

vi.mock('../../../services/environmentHealthService', () => ({
  environmentHealthService: {
    overview: vi.fn().mockResolvedValue({
      rows: [
      {
        environment_id: 1,
        environment_name: 'Production-EU',
        current_status: 'down',
        last_recorded_at: '2026-07-27T10:00:00Z',
        active_booking: true,
        active_booking_summary: {
          project_name: 'Project Alpha',
          start_date: '2026-07-27T08:00:00Z',
          end_date: '2026-07-27T18:00:00Z',
        },
        planned_outage: false,
        alert: true,
      },
      {
        environment_id: 2,
        environment_name: 'Staging-US',
        current_status: 'up',
        last_recorded_at: '2026-07-27T10:05:00Z',
        active_booking: false,
        active_booking_summary: null,
        planned_outage: false,
        alert: false,
      },
      ] satisfies EnvironmentHealthOverviewRow[],
      total: 2,
    }),
  },
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

function renderDashboard() {
  return render(
    <MemoryRouter>
      <HealthDashboard />
    </MemoryRouter>,
  );
}

describe('HealthDashboard', () => {
  it('shows an alert banner naming the alerting environment after data loads', async () => {
    renderDashboard();
    // Wait for the async fetch to resolve and the alert banner to appear
    const banner = await screen.findByRole('alert');
    expect(banner).toHaveTextContent('Production-EU');
  });

  it('renders a "down" status chip for the alerting environment', async () => {
    renderDashboard();
    expect(await screen.findByText('down')).toBeInTheDocument();
  });

  it('renders an "up" status chip for the healthy environment', async () => {
    renderDashboard();
    expect(await screen.findByText('up')).toBeInTheDocument();
  });

  it('names the alerting environment in the grid row', async () => {
    renderDashboard();
    expect(await screen.findByText('Production-EU')).toBeInTheDocument();
  });

  it('names the healthy environment in the grid row', async () => {
    renderDashboard();
    expect(await screen.findByText('Staging-US')).toBeInTheDocument();
  });
  it('says so when the overview was truncated, because the grid rows are derived from it', async () => {
    // GET /environments/health is capped server-side. This page's own table
    // rows are built from that fetch, so a truncated fetch can leave a row
    // out of the grid entirely — presenting that as the whole picture is the
    // bug this truncation banner exists to prevent.
    //
    // The page now has TWO independent callers of `overview()` per render —
    // its own table fetch, and the extracted `HealthAlertBanner`'s own fetch
    // (mounted as a child, so its effect fires first — see the note on
    // `HealthDashboard.tsx`). `mockResolvedValueOnce` is a FIFO queue on the
    // shared mock, so a single queued response would go to whichever
    // component's effect happens to run first, leaving the OTHER caller
    // reading the plain two-row default fixture below instead — exactly the
    // kind of ordering-dependent flake this file's lack of a
    // `mockReset`-per-test setup makes easy to introduce silently. Queuing
    // the same truncated response twice makes both callers see it,
    // regardless of firing order.
    const truncatedResponse = {
      rows: [
        {
          environment_id: 1,
          environment_name: 'Production-EU',
          current_status: 'up',
          last_recorded_at: '2026-07-27T10:00:00Z',
          active_booking: false,
          active_booking_summary: null,
          planned_outage: false,
          alert: false,
        },
      ] satisfies EnvironmentHealthOverviewRow[],
      total: 900,
    };
    vi.mocked(environmentHealthService.overview)
      .mockResolvedValueOnce(truncatedResponse)
      .mockResolvedValueOnce(truncatedResponse);

    renderDashboard();

    expect(await screen.findByText(/Showing 1 of 900 environments/)).toBeInTheDocument();
    expect(screen.getByText(/899 are not included/)).toBeInTheDocument();
  });

  it('says nothing about truncation when the whole set was returned', async () => {
    renderDashboard();
    await screen.findByText('Production-EU');
    expect(screen.queryByText(/are not included/)).not.toBeInTheDocument();
  });
});