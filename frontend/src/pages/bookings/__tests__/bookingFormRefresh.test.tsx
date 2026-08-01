import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import BookingForm from '../BookingForm';
import type { EnvironmentResponse } from '../../../types/environment';
import type { BookingTypeRecord } from '../../../types/bookingLifecycle';
import type { BookingRequestCreateResponse } from '../../../types/bookingRequest';

// No HTTP anywhere in this test — it's about which callback fires after a
// successful create, not about what the server returns.
vi.mock('../../../services/bookingRequestService', () => ({
  bookingRequestService: {
    create: vi.fn(),
    previewConflicts: vi.fn().mockResolvedValue({ conflicts: {} }),
  },
}));
vi.mock('../../../services/environmentService', () => ({
  environmentService: {
    listEnvironments: vi.fn(),
  },
}));
vi.mock('../../../services/bookingLifecycleService', () => ({
  bookingLifecycleService: {
    listBookingTypes: vi.fn(),
    listTemplates: vi.fn().mockResolvedValue([]),
  },
}));
vi.mock('../../../services/customFieldService', () => ({
  customFieldService: {
    listDefinitions: vi.fn().mockResolvedValue([]),
  },
}));
vi.mock('../../../services/tenantAdminService', () => ({
  tenantAdminService: {
    listUsers: vi.fn().mockResolvedValue([]),
  },
}));
// BookingForm doesn't touch this directly, but if the Finding-1 regression
// is reintroduced (a bare dispatch(fetchBookings())) it does, and an
// unmocked call would hit real HTTP.
vi.mock('../../../services/bookingService', () => ({
  bookingService: {
    listBookings: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

import { bookingRequestService } from '../../../services/bookingRequestService';
import { environmentService } from '../../../services/environmentService';
import { bookingLifecycleService } from '../../../services/bookingLifecycleService';

const ENV: EnvironmentResponse = {
  id: 1,
  name: 'Env A',
  description: null,
  environment_type: 'test',
  status: 'active',
  tenant_id: 1,
  custom_fields: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const BOOKING_TYPE: BookingTypeRecord = {
  id: 5,
  tenant_id: 1,
  name: 'Standard',
  description: null,
  lifecycle_template_id: 99,
  color: null,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const CREATE_RESPONSE: BookingRequestCreateResponse = {
  request: {
    id: 1,
    tenant_id: 1,
    project_name: 'Test Project',
    booking_type_id: 5,
    start_date: '2026-08-10T09:00:00Z',
    end_date: '2026-08-11T09:00:00Z',
    notes: null,
    context_tag: 'none',
    exclusive_use_requested: false,
    custom_fields: null,
    booked_by: 1,
    delegate_user_ids: null,
    rollup_status: 'draft',
    bookings: [
      {
        id: 42,
        environment_id: 1,
        environment_name: 'Env A',
        project_name: 'Test Project',
        start_date: '2026-08-10T09:00:00Z',
        end_date: '2026-08-11T09:00:00Z',
        status: 'draft',
      },
    ],
  },
  detected_conflicts: {},
};

async function fillAndSubmit() {
  const user = userEvent.setup();

  await user.click(screen.getByLabelText('Environments *'));
  await user.click(await screen.findByText('Env A'));

  // `required` on these fields makes MUI append a literal " *" to the
  // rendered label, so match loosely rather than the exact prop string.
  fireEventChange(screen.getByLabelText(/Project Name/), 'Test Project');
  fireEventChange(screen.getByLabelText(/Start Date & Time/), '2026-08-10T09:00');
  fireEventChange(screen.getByLabelText(/End Date & Time/), '2026-08-11T09:00');

  // Booking type auto-selects the first active type once bookingTypes load.
  await screen.findByText('Standard');

  await user.click(screen.getByRole('button', { name: 'Create Booking' }));
}

// react-hook-form's registered inputs need a native change event, not
// userEvent.type, to fire reliably for datetime-local/text fields here.
function fireEventChange(el: HTMLElement, value: string) {
  const input = el as HTMLInputElement;
  input.focus();
  Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!.call(
    input,
    value
  );
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
}

describe('BookingForm create-success refresh', () => {
  beforeEach(() => {
    vi.mocked(bookingRequestService.create).mockReset().mockResolvedValue(CREATE_RESPONSE);
    vi.mocked(environmentService.listEnvironments).mockResolvedValue({ rows: [ENV], total: 1 });
    vi.mocked(bookingLifecycleService.listBookingTypes).mockResolvedValue([BOOKING_TYPE]);

    // BookingForm now sources its environment picker from useAllEnvironments,
    // which calls environmentService.listEnvironments directly (mocked
    // above) rather than reading the shared slice — no store seeding needed.
  });

  it('calls onCreated instead of dispatching a bare, unparameterised fetchBookings', async () => {
    const dispatchSpy = vi.spyOn(store, 'dispatch');
    const onCreated = vi.fn();
    const onClose = vi.fn();

    render(
      <Provider store={store}>
        <MemoryRouter>
          <BookingForm open onClose={onClose} onCreated={onCreated} />
        </MemoryRouter>
      </Provider>
    );

    await fillAndSubmit();

    await waitFor(() => expect(bookingRequestService.create).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));

    // The regression this guards: BookingForm dispatching fetchBookings()
    // itself, which — now that BookingList's slice holds a server-paged,
    // filtered, sorted view — would silently overwrite it with the
    // endpoint's unfiltered page-1 default. The parent (BookingList /
    // BookingCalendar), not BookingForm, owns the correct refresh.
    const dispatchedBareFetchBookings = dispatchSpy.mock.calls.some(([action]) => {
      return (
        typeof action === 'object' &&
        action !== null &&
        'type' in action &&
        String((action as { type: unknown }).type).startsWith('booking/fetchBookings')
      );
    });
    expect(dispatchedBareFetchBookings).toBe(false);

    dispatchSpy.mockRestore();
  });
});
