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
import type { EnvironmentGroupResponse } from '../../../types/environmentGroup';

// Task 8: booking an EnvironmentGroup from the booking form. The behaviour
// under test throughout is that the form sends `environment_group_ids` and
// leaves group-membership expansion to the server — never expands a group's
// members into `environment_ids` itself, which would freeze membership at
// whatever the browser last fetched and duplicate a rule the server owns.

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
    listGroups: vi.fn(),
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
// Not touched directly by BookingForm, but a bare dispatch(fetchBookings())
// regression would hit it — kept mocked so that would fail loudly rather
// than making real HTTP.
vi.mock('../../../services/bookingService', () => ({
  bookingService: {
    listBookings: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

import { bookingRequestService } from '../../../services/bookingRequestService';
import { environmentService } from '../../../services/environmentService';
import { environmentGroupService } from '../../../services/environmentGroupService';
import { bookingLifecycleService } from '../../../services/bookingLifecycleService';

// Deliberately distinct ids/names from every other fixture in this file (and
// from the ids used in bookingFormRefresh.test.tsx) — a wrong-data-source
// bug (e.g. reading the group id where the env id belongs) must not pass by
// numeric or textual coincidence.
const ENV: EnvironmentResponse = {
  id: 501,
  name: 'Env Alpha',
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
  id: 77,
  tenant_id: 1,
  name: 'Standard',
  description: null,
  lifecycle_template_id: 200,
  color: null,
  is_active: true,
  default_protection_level: 'soft',
  default_duration_minutes: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const GROUP_A: EnvironmentGroupResponse = {
  id: 601,
  tenant_id: 1,
  name: 'Payments Squad',
  description: null,
  member_count: 3,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const GROUP_B: EnvironmentGroupResponse = {
  id: 602,
  tenant_id: 1,
  name: 'Data Squad',
  description: null,
  member_count: 2,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

function makeCreateResponse(): BookingRequestCreateResponse {
  return {
    request: {
      id: 1,
      tenant_id: 1,
      project_name: 'Test Project',
      project_id: null,
      project_name_link: null,
      booking_type_id: BOOKING_TYPE.id,
      start_date: '2026-08-10T09:00:00Z',
      end_date: '2026-08-11T09:00:00Z',
      notes: null,
      context_tag: 'none',
      exclusive_use_requested: false,
      protection_level: 'soft',
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

async function fillCommonFields() {
  const user = userEvent.setup();
  fireEventChange(screen.getByLabelText(/^Purpose/), 'Test Project');
  fireEventChange(screen.getByLabelText(/Start Date & Time/), '2026-08-10T09:00');
  fireEventChange(screen.getByLabelText(/End Date & Time/), '2026-08-11T09:00');
  await screen.findByText('Standard');
  return user;
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

describe('BookingForm — booking an environment group', () => {
  beforeEach(() => {
    snackbarError.mockReset();
    snackbarSuccess.mockReset();
    vi.mocked(bookingRequestService.create).mockReset().mockResolvedValue(makeCreateResponse());
    vi.mocked(environmentService.listEnvironments).mockResolvedValue({ rows: [ENV], total: 1 });
    vi.mocked(environmentGroupService.listGroups)
      .mockReset()
      .mockResolvedValue({ rows: [GROUP_A, GROUP_B], total: 2 });
    vi.mocked(bookingLifecycleService.listBookingTypes).mockResolvedValue([BOOKING_TYPE]);
  });

  it('sends environment_group_ids for a group-only selection, and does not expand it into environment_ids', async () => {
    renderForm();
    const user = await fillCommonFields();

    await user.click(screen.getByLabelText('Environment groups (optional)'));
    await user.click(await screen.findByText('Payments Squad'));

    await user.click(screen.getByRole('button', { name: 'Create Booking' }));

    await waitFor(() => expect(bookingRequestService.create).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(bookingRequestService.create).mock.calls[0][0];
    expect(payload.environment_group_ids).toEqual([GROUP_A.id]);
    // The whole point: no member of the group is expanded into environment_ids.
    // The form has no member list to expand from in the first place, but this
    // pins the wire contract regardless of how a regression might reintroduce it.
    expect(payload.environment_ids).toEqual([]);
  });

  it('a group alone is a valid submission — no "select an environment" client error blocks it', async () => {
    renderForm();
    const user = await fillCommonFields();

    await user.click(screen.getByLabelText('Environment groups (optional)'));
    await user.click(await screen.findByText('Payments Squad'));

    await user.click(screen.getByRole('button', { name: 'Create Booking' }));

    await waitFor(() => expect(bookingRequestService.create).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/Select at least one environment/)).not.toBeInTheDocument();
  });

  it('rejects a submission with neither an environment nor a group selected, client-side', async () => {
    renderForm();
    const user = await fillCommonFields();

    await user.click(screen.getByRole('button', { name: 'Create Booking' }));

    expect(
      await screen.findByText('Select at least one environment or environment group')
    ).toBeInTheDocument();
    expect(bookingRequestService.create).not.toHaveBeenCalled();
  });

  it('does not fold group membership into environment_ids when an environment is ALSO picked by hand', async () => {
    renderForm();
    const user = await fillCommonFields();

    await user.click(screen.getByLabelText('Environments *'));
    await user.click(await screen.findByText('Env Alpha'));

    await user.click(screen.getByLabelText('Environment groups (optional)'));
    await user.click(await screen.findByText('Payments Squad'));

    await user.click(screen.getByRole('button', { name: 'Create Booking' }));

    await waitFor(() => expect(bookingRequestService.create).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(bookingRequestService.create).mock.calls[0][0];
    // Exactly the hand-picked environment — nothing added on the group's behalf.
    expect(payload.environment_ids).toEqual([ENV.id]);
    expect(payload.environment_group_ids).toEqual([GROUP_A.id]);
  });

  it('requests only active groups for the picker', async () => {
    renderForm();
    await waitFor(() =>
      expect(environmentGroupService.listGroups).toHaveBeenCalledWith(
        expect.objectContaining({ is_active: true })
      )
    );
  });

  it('says a group books all of its current environments, approved/rejected together', async () => {
    renderForm();
    expect(
      await screen.findByText(
        /Booking a group books all of its current environments; they will be approved or rejected together\./
      )
    ).toBeInTheDocument();
  });

  it('tells the user the group list is truncated rather than silently showing a partial list', async () => {
    vi.mocked(environmentGroupService.listGroups).mockReset().mockResolvedValue({
      rows: [GROUP_A],
      total: 5,
    });
    renderForm();
    expect(
      await screen.findByText('Only the first 1 environment groups are shown.')
    ).toBeInTheDocument();
  });

  it('does not claim truncation when every group was fetched', async () => {
    renderForm();
    await screen.findByText('Standard');
    expect(screen.queryByText(/environment groups are shown/)).not.toBeInTheDocument();
  });

  it('surfaces an overlap refusal from result.payload — both group names visible, generic status text absent', async () => {
    // Shaped like a real AxiosError: `.message` is the generic HTTP-status
    // text RTK's default serialisation would fall back to if the thunk read
    // `result.error.message` instead of `result.payload`.
    vi.mocked(bookingRequestService.create).mockReset().mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 400',
      response: {
        status: 400,
        data: {
          detail:
            "Environment 'Env Alpha' is reachable via both group 'Payments Squad' and group 'Data Squad'",
        },
      },
    });

    renderForm();
    const user = await fillCommonFields();

    await user.click(screen.getByLabelText('Environment groups (optional)'));
    await user.click(await screen.findByText('Payments Squad'));
    await user.click(screen.getByLabelText('Environment groups (optional)'));
    await user.click(await screen.findByText('Data Squad'));

    await user.click(screen.getByRole('button', { name: 'Create Booking' }));

    await waitFor(() => expect(bookingRequestService.create).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(snackbarError).toHaveBeenCalledTimes(1));

    const shown = snackbarError.mock.calls[0][0] as string;
    expect(shown).toContain('Payments Squad');
    expect(shown).toContain('Data Squad');
    expect(shown).not.toContain('Request failed with status code');
  });
});
