/**
 * A3 Task 6 — what the booking form does with the `agreement_gaps` the create
 * envelope comes back with.
 *
 * A3 WARNS, IT NEVER BLOCKS: a returned gap must not stop the create, must not
 * hold the dialog open, and must not suppress the success path. Every
 * assertion here pairs "the gap was surfaced" with "the create completed
 * exactly as it does without one".
 *
 * The gap message is the SERVER's, verbatim — agreement_gap_service names the
 * project and the environment in it and never falls back to an id. The form's
 * own job is to surface ONE message per gap, so a multi-environment request
 * tells the user WHICH environments are in gap rather than that "something" is.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import BookingForm from '../BookingForm';
import type { EnvironmentResponse } from '../../../types/environment';
import type { BookingTypeRecord } from '../../../types/bookingLifecycle';
import type {
  BookingRequestCreateResponse,
  EnvBookingSummary,
} from '../../../types/bookingRequest';

const snackbarError = vi.fn();
const snackbarSuccess = vi.fn();
const snackbarWarning = vi.fn();

vi.mock('../../../hooks/useSnackbar', () => ({
  useSnackbar: () => ({
    success: snackbarSuccess,
    error: snackbarError,
    info: vi.fn(),
    warning: snackbarWarning,
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
  environmentService: { listEnvironments: vi.fn() },
}));
vi.mock('../../../services/environmentGroupService', () => ({
  environmentGroupService: { listGroups: vi.fn().mockResolvedValue({ rows: [], total: 0 }) },
}));
vi.mock('../../../services/bookingLifecycleService', () => ({
  bookingLifecycleService: {
    listBookingTypes: vi.fn(),
    listTemplates: vi.fn().mockResolvedValue([]),
  },
}));
vi.mock('../../../services/customFieldService', () => ({
  customFieldService: { listDefinitions: vi.fn().mockResolvedValue([]) },
}));
vi.mock('../../../services/tenantAdminService', () => ({
  tenantAdminService: { listUsers: vi.fn().mockResolvedValue({ rows: [], total: 0 }) },
}));
vi.mock('../../../services/projectService', () => ({
  projectService: { listProjects: vi.fn().mockResolvedValue({ rows: [], total: 0 }) },
}));
vi.mock('../../../services/bookingService', () => ({
  bookingService: { listBookings: vi.fn().mockResolvedValue({ rows: [], total: 0 }) },
}));

import { bookingRequestService } from '../../../services/bookingRequestService';
import { environmentService } from '../../../services/environmentService';
import { bookingLifecycleService } from '../../../services/bookingLifecycleService';

// Ids distinct from bookingFormGroups (envs 501, groups 60x) and
// bookingFormRefresh (env 1, booking 42).
const STAGING_ID = 5101;
const INTEGRATION_ID = 5102;
const STAGING_BOOKING_ID = 5201;
const INTEGRATION_BOOKING_ID = 5202;

const STAGING_GAP =
  "Mortgage Replatform's booking falls outside its agreed window for Staging (1 Jan 2026 – 30 Jun 2026)";
const INTEGRATION_GAP = 'Mortgage Replatform has no usage agreement for Integration';

function environment(id: number, name: string): EnvironmentResponse {
  return {
    id,
    name,
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
}

const STAGING = environment(STAGING_ID, 'Staging');
const INTEGRATION = environment(INTEGRATION_ID, 'Integration');

const BOOKING_TYPE: BookingTypeRecord = {
  id: 55,
  tenant_id: 1,
  name: 'Standard',
  description: null,
  lifecycle_template_id: 99,
  color: null,
  is_active: true,
  default_protection_level: 'soft',
  default_duration_minutes: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

function envBooking(
  id: number,
  environmentId: number,
  name: string,
  gap: string | null
): EnvBookingSummary {
  return {
    has_unacknowledged_conflicts: false,
    id,
    environment_id: environmentId,
    environment_name: name,
    project_name: 'Regression sweep',
    start_date: '2026-08-10T09:00:00Z',
    end_date: '2026-08-11T09:00:00Z',
    status: 'draft',
    protection_level: 'soft',
    agreement_gap: gap,
    has_unacknowledged_agreement_gap: gap != null,
    environment_group_id: null,
    environment_group_name: null,
  };
}

function makeCreateResponse(gaps: Record<number, string>): BookingRequestCreateResponse {
  return {
    request: {
      id: 4001,
      tenant_id: 1,
      project_name: 'Regression sweep',
      project_id: 31,
      project_name_link: 'Mortgage Replatform',
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
      bookings: [
        envBooking(STAGING_BOOKING_ID, STAGING_ID, 'Staging', gaps[STAGING_BOOKING_ID] ?? null),
        envBooking(
          INTEGRATION_BOOKING_ID,
          INTEGRATION_ID,
          'Integration',
          gaps[INTEGRATION_BOOKING_ID] ?? null
        ),
      ],
    },
    detected_conflicts: {},
    agreement_gaps: gaps,
  };
}

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

async function fillAndSubmit() {
  const user = userEvent.setup();
  await user.click(screen.getByLabelText('Environments *'));
  await user.click(await screen.findByText('Staging'));
  await user.click(screen.getByLabelText('Environments *'));
  await user.click(await screen.findByText('Integration'));

  fireEventChange(screen.getByLabelText(/^Purpose/), 'Regression sweep');
  fireEventChange(screen.getByLabelText(/Start Date & Time/), '2026-08-10T09:00');
  fireEventChange(screen.getByLabelText(/End Date & Time/), '2026-08-11T09:00');
  await screen.findByText('Standard');

  await user.click(screen.getByRole('button', { name: 'Create Booking' }));
}

function renderForm(onCreated = vi.fn(), onClose = vi.fn()) {
  render(
    <Provider store={store}>
      <MemoryRouter>
        <BookingForm open onClose={onClose} onCreated={onCreated} />
      </MemoryRouter>
    </Provider>
  );
  return { onCreated, onClose };
}

beforeEach(() => {
  snackbarError.mockReset();
  snackbarSuccess.mockReset();
  snackbarWarning.mockReset();
  vi.mocked(bookingRequestService.create).mockReset().mockResolvedValue(makeCreateResponse({}));
  vi.mocked(environmentService.listEnvironments).mockResolvedValue({
    rows: [STAGING, INTEGRATION],
    total: 2,
  });
  vi.mocked(bookingLifecycleService.listBookingTypes).mockResolvedValue([BOOKING_TYPE]);
});

describe('BookingForm — usage-agreement gaps on the create response', () => {
  it('surfaces one warning per returned gap, naming each environment', async () => {
    vi.mocked(bookingRequestService.create).mockResolvedValue(
      makeCreateResponse({
        [STAGING_BOOKING_ID]: STAGING_GAP,
        [INTEGRATION_BOOKING_ID]: INTEGRATION_GAP,
      })
    );
    renderForm();
    await fillAndSubmit();

    await waitFor(() => expect(snackbarWarning).toHaveBeenCalledTimes(2));
    const shown = snackbarWarning.mock.calls.map((c) => c[0] as string);
    // Not a single "some bookings have gaps" summary: each environment in gap
    // is named, so the user knows which ones to get an agreement for.
    expect(shown.some((m) => m.includes('Staging'))).toBe(true);
    expect(shown.some((m) => m.includes('Integration'))).toBe(true);
    expect(shown).toContain(STAGING_GAP);
    expect(shown).toContain(INTEGRATION_GAP);
  });

  it('creates the booking anyway — a gap warns, it never blocks', async () => {
    vi.mocked(bookingRequestService.create).mockResolvedValue(
      makeCreateResponse({ [STAGING_BOOKING_ID]: STAGING_GAP })
    );
    const { onCreated, onClose } = renderForm();
    await fillAndSubmit();

    await waitFor(() => expect(bookingRequestService.create).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    expect(snackbarSuccess).toHaveBeenCalledWith('Booking created');
    // The dialog closes exactly as it does with no gap — nothing is held open
    // pending an acknowledgement.
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(snackbarError).not.toHaveBeenCalled();
  });

  it('says nothing when the create returns no gaps', async () => {
    renderForm();
    await fillAndSubmit();

    await waitFor(() => expect(bookingRequestService.create).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(snackbarSuccess).toHaveBeenCalledTimes(1));
    expect(snackbarWarning).not.toHaveBeenCalled();
  });
});
