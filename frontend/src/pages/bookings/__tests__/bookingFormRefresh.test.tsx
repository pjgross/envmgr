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
    listUsers: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));
vi.mock('../../../services/projectService', () => ({
  projectService: {
    listProjects: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
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
import { projectService } from '../../../services/projectService';

const ENV: EnvironmentResponse = {
  id: 1,
  name: 'Env A',
  description: null,
  tier_id: 2,
  tier_name: 'Test',
  tier_color: null,
  owner_user_id: 9,
  owner_username: 'owner',
  expires_at: null,
  reserved_now: false,
  status: 'active',
  tenant_id: 1,
  custom_fields: null,
  operations_group_id: null,
  operations_group_name: null,
  access_url: null,
  connection_notes: null,
  support_contact: null,
  sla_notes: null,
  known_limitations: null,
  decommission_notes: null,
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
    project_id: null,
    project_name_link: null,
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
        environment_group_id: null,
        environment_group_name: null,
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
  fireEventChange(screen.getByLabelText(/^Purpose/), 'Test Project');
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

const PROJECT = {
  id: 3,
  tenant_id: 1,
  name: 'Mortgage',
  code: 'MTG',
  description: null,
  team_group_id: null,
  team_group_name: null,
  environment_count: 0,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

describe('BookingForm create-success refresh', () => {
  beforeEach(() => {
    vi.mocked(bookingRequestService.create).mockReset().mockResolvedValue(CREATE_RESPONSE);
    vi.mocked(environmentService.listEnvironments).mockResolvedValue({ rows: [ENV], total: 1 });
    vi.mocked(bookingLifecycleService.listBookingTypes).mockResolvedValue([BOOKING_TYPE]);
    vi.mocked(projectService.listProjects).mockReset().mockResolvedValue({
      rows: [PROJECT],
      total: 1,
    });

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

// Task 7: the Project picker (linked project_id) and the Purpose relabel
// (the pre-existing free-text projectName field). The two are different
// values on the wire — conflating them is the bug these tests exist to catch.
describe('BookingForm project picker and Purpose relabel', () => {
  beforeEach(() => {
    vi.mocked(bookingRequestService.create).mockReset().mockResolvedValue(CREATE_RESPONSE);
    vi.mocked(environmentService.listEnvironments).mockResolvedValue({ rows: [ENV], total: 1 });
    vi.mocked(bookingLifecycleService.listBookingTypes).mockResolvedValue([BOOKING_TYPE]);
    vi.mocked(projectService.listProjects).mockReset().mockResolvedValue({
      rows: [PROJECT],
      total: 1,
    });
  });

  function renderForm() {
    return render(
      <Provider store={store}>
        <MemoryRouter>
          <BookingForm open onClose={vi.fn()} />
        </MemoryRouter>
      </Provider>
    );
  }

  it('labels the free-text field "Purpose", not "Project Name"', async () => {
    renderForm();
    expect(await screen.findByLabelText(/^Purpose/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Project Name/)).not.toBeInTheDocument();
  });

  it('fetches only active projects for the picker (drops is_active: true otherwise)', async () => {
    renderForm();
    await waitFor(() =>
      expect(projectService.listProjects).toHaveBeenCalledWith(
        expect.objectContaining({ is_active: true })
      )
    );
  });

  it('sends project_id when a project is chosen, and project_name stays the Purpose text', async () => {
    const user = userEvent.setup();
    renderForm();

    await user.click(screen.getByLabelText('Environments *'));
    await user.click(await screen.findByText('Env A'));

    await user.click(screen.getByLabelText('Project (optional)'));
    await user.click(await screen.findByText('Mortgage'));

    fireEventChange(screen.getByLabelText(/^Purpose/), 'Regression sweep');
    fireEventChange(screen.getByLabelText(/Start Date & Time/), '2026-08-10T09:00');
    fireEventChange(screen.getByLabelText(/End Date & Time/), '2026-08-11T09:00');

    await screen.findByText('Standard');
    await user.click(screen.getByRole('button', { name: 'Create Booking' }));

    await waitFor(() => expect(bookingRequestService.create).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(bookingRequestService.create).mock.calls[0][0];
    // The two are different values — sending one where the other belongs is
    // the bug this test exists to prevent.
    expect(payload.project_id).toBe(PROJECT.id);
    expect(payload.project_name).toBe('Regression sweep');
  });

  it('omits project_id entirely when no project is chosen', async () => {
    renderForm();
    await fillAndSubmit();

    await waitFor(() => expect(bookingRequestService.create).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(bookingRequestService.create).mock.calls[0][0];
    expect(payload.project_id).toBeUndefined();
    expect(payload.project_name).toBe('Test Project');
  });
});
