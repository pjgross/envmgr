import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import { setCredentials } from '../../../store/authSlice';
import BookingForm from '../BookingForm';
import type { EnvironmentResponse } from '../../../types/environment';
import type { BookingTypeRecord } from '../../../types/bookingLifecycle';
import type { BookingRequestCreateResponse } from '../../../types/bookingRequest';

// B4 on the booking form: the duration preset fills the end date, and the
// protection level is shown to everyone but changeable only by an Admin or
// Release Manager. The carve-out on the server side (an unchanged value is
// always accepted) exists precisely so the read-only case can still submit
// the field — the last test here is the half that exercises it.

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
vi.mock('../../../services/environmentGroupService', () => ({
  environmentGroupService: {
    listGroups: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
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
vi.mock('../../../services/bookingService', () => ({
  bookingService: {
    listBookings: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

import { bookingRequestService } from '../../../services/bookingRequestService';
import { environmentService } from '../../../services/environmentService';
import { bookingLifecycleService } from '../../../services/bookingLifecycleService';

const ENV: EnvironmentResponse = {
  id: 8801,
  name: 'SIT',
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
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
} as any;

// HALF_DAY is listed first so it is the type auto-selected on mount: every
// assertion about "the user picked Release cycle" is then a real change, not
// the initial state passing by luck.
const HALF_DAY: BookingTypeRecord = {
  id: 8901,
  tenant_id: 1,
  name: 'Half day',
  description: null,
  lifecycle_template_id: 1,
  color: null,
  is_active: true,
  default_protection_level: 'soft',
  default_duration_minutes: 240,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const RELEASE_CYCLE: BookingTypeRecord = {
  ...HALF_DAY,
  id: 8902,
  name: 'Release cycle',
  default_protection_level: 'hard',
  default_duration_minutes: 20160,
};

function makeCreateResponse(): BookingRequestCreateResponse {
  return {
    request: {
      id: 8001,
      tenant_id: 1,
      project_name: 'Regression sweep',
      project_id: null,
      project_name_link: null,
      booking_type_id: RELEASE_CYCLE.id,
      start_date: '2026-09-01T09:00:00Z',
      end_date: '2026-09-15T09:00:00Z',
      notes: null,
      context_tag: 'none',
      exclusive_use_requested: false,
      protection_level: 'hard',
      custom_fields: null,
      booked_by: 1,
      delegate_user_ids: null,
      rollup_status: 'draft',
      bookings: [],
    },
    detected_conflicts: {},
    agreement_gaps: {},
  };
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

/** Seed the real store's auth state — the form reads `s.auth.user`. */
function signInAs(role: string) {
  store.dispatch(
    setCredentials({
      user: {
        id: 1,
        username: 'tester',
        email: 'tester@test.com',
        role,
        tenant_id: 1,
        is_active: true,
        is_master_admin: false,
      } as never,
      token: 'test-token',
    })
  );
}

function renderForm() {
  return render(
    <Provider store={store}>
      <MemoryRouter>
        <BookingForm open onClose={vi.fn()} />
      </MemoryRouter>
    </Provider>
  );
}

async function pickBookingType(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(screen.getByLabelText(/booking type/i));
  await user.click(await screen.findByRole('option', { name }));
}

describe('BookingForm — B4', () => {
  beforeEach(() => {
    snackbarError.mockReset();
    snackbarSuccess.mockReset();
    vi.mocked(bookingRequestService.create).mockReset().mockResolvedValue(makeCreateResponse());
    vi.mocked(environmentService.listEnvironments).mockResolvedValue({ rows: [ENV], total: 1 });
    vi.mocked(bookingLifecycleService.listBookingTypes).mockResolvedValue([
      HALF_DAY,
      RELEASE_CYCLE,
    ]);
  });

  it('fills the end date from the booking type preset', async () => {
    signInAs('Admin');
    const user = userEvent.setup();
    renderForm();
    await screen.findByText('Half day');

    fireEventChange(screen.getByLabelText(/Start Date & Time/), '2026-09-01T09:00');
    await pickBookingType(user, 'Half day');

    await waitFor(() =>
      expect(screen.getByLabelText(/End Date & Time/)).toHaveValue('2026-09-01T13:00')
    );
  });

  it('does NOT overwrite an end date the user already edited', async () => {
    // A preset that clobbers a deliberate choice is worse than no preset.
    signInAs('Admin');
    const user = userEvent.setup();
    renderForm();
    await screen.findByText('Half day');

    fireEventChange(screen.getByLabelText(/Start Date & Time/), '2026-09-01T09:00');
    fireEventChange(screen.getByLabelText(/End Date & Time/), '2026-09-30T17:00');
    await pickBookingType(user, 'Half day');

    await waitFor(() =>
      expect(screen.getByLabelText(/End Date & Time/)).toHaveValue('2026-09-30T17:00')
    );
  });

  it('shows a non-admin their inherited level read-only, not hidden', async () => {
    // A user should be able to SEE that their release-cycle booking is
    // protected, even though they cannot change it.
    signInAs('Developer');
    const user = userEvent.setup();
    renderForm();
    await screen.findByText('Half day');

    await pickBookingType(user, 'Release cycle');

    const control = await screen.findByLabelText(/protection/i);
    expect(control).toBeInTheDocument();
    expect(screen.getByText('Protected')).toBeInTheDocument();
    expect(control).toHaveAttribute('aria-disabled', 'true');
  });

  it('lets an Admin choose a level', async () => {
    signInAs('Admin');
    const user = userEvent.setup();
    renderForm();
    await screen.findByText('Half day');

    await pickBookingType(user, 'Half day');
    await user.click(screen.getByLabelText(/protection/i));
    await user.click(await screen.findByRole('option', { name: 'Protected' }));

    expect(screen.getByLabelText(/protection/i)).not.toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByText('Protected')).toBeInTheDocument();
  });

  it('submits the inherited level unchanged for a non-admin', async () => {
    // THE CARVE-OUT'S UI HALF. The form sends protection_level even when the
    // user cannot change it, and the server accepts it because it matches the
    // booking type's default. If this stops being sent, the backend carve-out
    // is untested from the side that actually exercises it.
    signInAs('Developer');
    const user = userEvent.setup();
    renderForm();
    await screen.findByText('Half day');

    fireEventChange(screen.getByLabelText(/^Purpose/), 'Regression sweep');
    fireEventChange(screen.getByLabelText(/Start Date & Time/), '2026-09-01T09:00');
    await pickBookingType(user, 'Release cycle');
    await user.click(screen.getByLabelText('Environments *'));
    await user.click(await screen.findByText('SIT'));
    await user.click(screen.getByRole('button', { name: 'Create Booking' }));

    await waitFor(() => expect(bookingRequestService.create).toHaveBeenCalledTimes(1));
    expect(vi.mocked(bookingRequestService.create).mock.calls[0][0]).toEqual(
      expect.objectContaining({ protection_level: 'hard' })
    );
  });
});
