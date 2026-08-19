/**
 * B5 fix wave item 1: `assert_bookable`'s decommission refusal is a string
 * HTTPException detail, not the {"message", "conflicts"} shape an
 * exclusive-use overlap raises. `bulk_book_environments` now carries that
 * string through as `reason` on the skipped entry, and the dialog must
 * render the REAL refusal reason per environment rather than asserting
 * "exclusive conflict" for every skip.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { store } from '../../../store';
import BulkBookEnvironmentsDialog from '../BulkBookEnvironmentsDialog';
import type { EnvironmentResponse } from '../../../types/environment';
import type { BookingTypeRecord } from '../../../types/bookingLifecycle';

const snackbarError = vi.fn();
const snackbarSuccess = vi.fn();

vi.mock('../../../hooks/useSnackbar', () => ({
  useSnackbar: () => ({
    success: snackbarSuccess,
    error: snackbarError,
    info: vi.fn(),
    warning: vi.fn(),
    show: vi.fn(),
  }),
}));

vi.mock('../../../hooks/useAllEnvironments', () => ({
  useAllEnvironments: () => ({
    environments: [
      { id: 1, name: 'A' } as EnvironmentResponse,
      { id: 2, name: 'B' } as EnvironmentResponse,
    ],
    loading: false,
    truncated: false,
  }),
}));

vi.mock('../../../services/releaseService', () => ({
  releaseService: { bulkBookEnvironments: vi.fn() },
}));

vi.mock('../../../services/bookingRequestService', () => ({
  bookingRequestService: { previewConflicts: vi.fn() },
}));

vi.mock('../../../services/bookingLifecycleService', () => ({
  bookingLifecycleService: { listBookingTypes: vi.fn() },
}));

import { releaseService } from '../../../services/releaseService';
import { bookingLifecycleService } from '../../../services/bookingLifecycleService';

const BOOKING_TYPE: BookingTypeRecord = {
  id: 1,
  tenant_id: 1,
  name: 'Standard',
  description: null,
  lifecycle_template_id: 1,
  color: null,
  is_active: true,
  default_protection_level: 'soft',
  default_duration_minutes: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

async function fillAndSubmit() {
  await userEvent.click(screen.getByRole('combobox', { name: /booking type/i }));
  await userEvent.click(await screen.findByRole('option', { name: 'Standard' }));

  await userEvent.type(screen.getByLabelText(/^Purpose/), 'Release booking');

  const start = screen.getByLabelText(/^Start Date/) as HTMLInputElement;
  const end = screen.getByLabelText(/^End Date/) as HTMLInputElement;
  await userEvent.type(start, '2026-08-01');
  await userEvent.type(end, '2026-08-02');

  await userEvent.click(screen.getByRole('button', { name: /^book$/i }));
}

describe('BulkBookEnvironmentsDialog — skip reasons', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (bookingLifecycleService.listBookingTypes as ReturnType<typeof vi.fn>).mockResolvedValue([BOOKING_TYPE]);
  });

  it('renders the real decommission refusal reason, not "exclusive conflict"', async () => {
    (releaseService.bulkBookEnvironments as ReturnType<typeof vi.fn>).mockResolvedValue({
      created: [{ environment_id: 2, booking_id: 5, warnings: [] }],
      skipped: [{
        environment_id: 1,
        conflicts: [],
        reason: 'A is scheduled to be torn down on 2026-08-01 — this booking runs past that date',
      }],
    });

    render(
      <Provider store={store}>
        <BulkBookEnvironmentsDialog
          open
          onClose={vi.fn()}
          releaseId={1}
          environmentIds={[1, 2]}
          phases={[]}
          onCreated={vi.fn()}
        />
      </Provider>
    );

    await screen.findByRole('option', { name: 'Standard' }).catch(() => {});
    await fillAndSubmit();

    expect(await screen.findByText(/scheduled to be torn down/i)).toBeInTheDocument();
    expect(screen.queryByText(/exclusive conflict/i)).not.toBeInTheDocument();
  });

  it('still labels an exclusive-use skip as an exclusive conflict when no reason is sent', async () => {
    (releaseService.bulkBookEnvironments as ReturnType<typeof vi.fn>).mockResolvedValue({
      created: [],
      skipped: [{ environment_id: 1, conflicts: [42] }],
    });

    render(
      <Provider store={store}>
        <BulkBookEnvironmentsDialog
          open
          onClose={vi.fn()}
          releaseId={1}
          environmentIds={[1]}
          phases={[]}
          onCreated={vi.fn()}
        />
      </Provider>
    );

    await fillAndSubmit();

    expect(await screen.findByText(/exclusive conflict/i)).toBeInTheDocument();
  });
});
