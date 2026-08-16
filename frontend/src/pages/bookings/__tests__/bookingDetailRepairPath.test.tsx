/**
 * The group repair path, end to end, with the REAL `GroupTransitionPanel` and
 * `EnvironmentsPanel` mounted inside `BookingDetail`.
 *
 * WHY THIS FILE EXISTS, AND WHY IT MUST NOT BE MADE TO LOOK LIKE ITS
 * NEIGHBOUR: `bookingDetailGroupPanels.test.tsx` mocks both panels down to
 * the props BookingDetail passes them, and `GroupTransitionPanel.test.tsx`
 * feeds the panel its props by hand. Both ends of the seam were tested and
 * the join was not — deleting `onMemberTransition={handleMemberTransition}`
 * from BookingDetail left the entire frontend suite green while the repair
 * path regressed in full (the per-member buttons still render; clicking one
 * silently no-ops through `void onMemberTransition?.(...)`). That mocking is
 * exactly what hid the original defect, so this file deliberately does not
 * adopt it.
 *
 * What is at stake is the branch's central design argument. A2 keeps
 * `POST /bookings/{id}/transition` open on a group member specifically so a
 * diverged group is repairable rather than stuck; if that is unreachable from
 * the page that reports the divergence, a diverged group IS stuck, and the
 * "mixed terminal state is legitimate" adjudication stops holding.
 *
 * Only ConflictsPanel and the leaf services are stubbed — never the two
 * panels whose wiring is the thing under test.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { store } from '../../../store';
import type { BookingResponse } from '../../../types/booking';
import type { BookingRequestResponse, EnvBookingSummary } from '../../../types/bookingRequest';

// Makes its own fetches and is irrelevant to the repair path — stubbed to
// keep this file's failures about the wiring under test.
vi.mock('../../../components/bookings/ConflictsPanel', () => ({
  default: () => <div data-testid="conflicts-panel" />,
}));

vi.mock('../../../services/bookingService', () => ({
  bookingService: {
    getBooking: vi.fn(),
    getAllowedTransitions: vi.fn(),
    getHistory: vi.fn().mockResolvedValue([]),
    transitionState: vi.fn(),
  },
}));
vi.mock('../../../services/bookingRequestService', () => ({
  bookingRequestService: { get: vi.fn() },
}));
vi.mock('../../../services/environmentGroupService', () => ({
  environmentGroupService: {
    groupAllowedTransitions: vi.fn(),
    transitionGroup: vi.fn(),
  },
}));
vi.mock('../../../services/bookingLifecycleService', () => ({
  bookingLifecycleService: {
    listBookingTypes: vi.fn().mockResolvedValue([]),
    listTemplates: vi.fn().mockResolvedValue([]),
  },
}));
vi.mock('../../../services/customFieldService', () => ({
  customFieldService: { listDefinitions: vi.fn().mockResolvedValue([]) },
}));
vi.mock('../../../services/environmentService', () => ({
  environmentService: { listEnvironments: vi.fn().mockResolvedValue({ rows: [], total: 0 }) },
}));

import { bookingService } from '../../../services/bookingService';
import { bookingRequestService } from '../../../services/bookingRequestService';
import { environmentGroupService } from '../../../services/environmentGroupService';
import BookingDetail from '../BookingDetail';

// Deliberately distinct id ranges from every other fixture exercising this
// area (bookingDetailGroupPanels.tsx uses request 9001 / bookings 91xx /
// groups 601x; GroupTransitionPanel.test.tsx uses request 7301 / group 7401)
// so a wrong-data-source bug cannot pass by numeric coincidence. Environment
// ids differ from booking ids for the same reason: a control or a link built
// from the wrong one of the two must not land on a plausible value.
const REQUEST_ID = 9501;
const ALPHA_BOOKING_ID = 9601; // the odd one out, and the page we mount
const BETA_BOOKING_ID = 9602; // its sibling, already moved on
const GROUP_ID = 6511;
const GROUP_NAME = 'Payments Squad';

function envBooking(overrides: Partial<EnvBookingSummary>): EnvBookingSummary {
  return {
    has_unacknowledged_conflicts: false,
    id: 0,
    environment_id: 0,
    environment_name: null,
    project_name: 'Regression sweep',
    start_date: '2026-08-10T09:00:00Z',
    end_date: '2026-08-11T09:00:00Z',
    status: 'submitted',
    protection_level: 'soft',
    agreement_gap: null,
    has_unacknowledged_agreement_gap: false,
    environment_group_id: null,
    environment_group_name: null,
    ...overrides,
  };
}

const ALPHA_DRAFT = envBooking({
  id: ALPHA_BOOKING_ID,
  environment_id: 8501,
  environment_name: 'Alpha Env',
  status: 'draft',
  environment_group_id: GROUP_ID,
  environment_group_name: GROUP_NAME,
});
const ALPHA_APPROVED: EnvBookingSummary = { ...ALPHA_DRAFT, status: 'approved' };
const BETA_APPROVED = envBooking({
  id: BETA_BOOKING_ID,
  environment_id: 8502,
  environment_name: 'Beta Env',
  status: 'approved',
  environment_group_id: GROUP_ID,
  environment_group_name: GROUP_NAME,
});

function makeBooking(status = 'draft'): BookingResponse {
  return {
    id: ALPHA_BOOKING_ID,
    environment_id: 8501,
    environment_name: 'Alpha Env',
    project_name: 'Checkout release',
    project_id: null,
    project_name_link: null,
    booked_by: 1,
    booked_by_username: 'alice',
    start_date: '2026-08-10T09:00:00Z',
    end_date: '2026-08-11T09:00:00Z',
    booking_type_id: 5,
    exclusive_use: false,
    status,
    notes: null,
    recurrence_rule: null,
    recurrence_parent_id: null,
    release_id: null,
    test_phase_id: null,
    context_tag: 'none',
    custom_fields: null,
    environment_group_id: GROUP_ID,
    environment_group_name: GROUP_NAME,
    tenant_id: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    booking_request_id: REQUEST_ID,
    request: {
      id: REQUEST_ID,
      project_name: 'Checkout release',
      booking_type_id: 5,
      booked_by: 1,
      delegate_user_ids: null,
    },
  } as BookingResponse;
}

function makeRequest(bookings: EnvBookingSummary[]): BookingRequestResponse {
  return {
    id: REQUEST_ID,
    tenant_id: 1,
    project_name: 'Checkout release',
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
    rollup_status: 'mixed',
    bookings,
  } as BookingRequestResponse;
}

function renderPage() {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[`/bookings/${ALPHA_BOOKING_ID}`]}>
        <Routes>
          <Route path="/bookings/:id" element={<BookingDetail />} />
        </Routes>
      </MemoryRouter>
    </Provider>
  );
}

// A diverged group: Alpha still `draft`, Beta already `approved`, so the
// group's own intersection is empty and only the individual endpoint can
// move anything.
beforeEach(() => {
  vi.mocked(bookingService.getBooking).mockReset().mockResolvedValue(makeBooking());
  vi.mocked(bookingService.transitionState).mockReset().mockResolvedValue({} as never);
  vi.mocked(bookingRequestService.get)
    .mockReset()
    .mockResolvedValue(makeRequest([ALPHA_DRAFT, BETA_APPROVED]));
  vi.mocked(bookingService.getAllowedTransitions)
    .mockReset()
    .mockImplementation(async (id: number) =>
      id === ALPHA_BOOKING_ID
        ? [{ from_state: 'draft', to_state: 'approved', label: 'Approve Individually' }]
        : []
    );
  vi.mocked(environmentGroupService.groupAllowedTransitions).mockReset().mockResolvedValue([]);
});

describe('BookingDetail — the group repair path is reachable', () => {
  it('offers a per-booking transition control for the group member the page is mounted for', async () => {
    renderPage();

    // Confirms we are in the divergence scenario, not merely on a quiet page.
    await waitFor(() => expect(screen.getByText(/Members are out of step/i)).toBeInTheDocument());

    expect(
      await screen.findAllByRole('button', { name: 'Approve Individually' })
    ).not.toHaveLength(0);
  });

  it('links each sibling member, so the odd one out can be opened and repaired from here', async () => {
    renderPage();

    await waitFor(() => expect(screen.getByText(/Members are out of step/i)).toBeInTheDocument());

    // Not just "a link exists" — it must point at the SIBLING's booking, which
    // is the whole reason the link is here rather than on its own page.
    const link = await screen.findByRole('link', { name: 'Beta Env' });
    expect(link).toHaveAttribute('href', `/bookings/${BETA_BOOKING_ID}`);
  });
});

describe('BookingDetail — the repair loop closes', () => {
  it('repairing the odd member from the group panel restores the group control set and clears the notice', async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => expect(screen.getByText(/Members are out of step/i)).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Close Group' })).not.toBeInTheDocument();
    expect(environmentGroupService.groupAllowedTransitions).toHaveBeenCalledTimes(1);

    // What the server will say once Alpha has been brought back into step.
    vi.mocked(bookingRequestService.get).mockResolvedValue(
      makeRequest([ALPHA_APPROVED, BETA_APPROVED])
    );
    vi.mocked(bookingService.getBooking).mockResolvedValue(makeBooking('approved'));
    vi.mocked(bookingService.getAllowedTransitions).mockResolvedValue([]);
    vi.mocked(environmentGroupService.groupAllowedTransitions).mockResolvedValue([
      { from_state: 'approved', to_state: 'closed', label: 'Close Group' },
    ]);

    await user.click((await screen.findAllByRole('button', { name: 'Approve Individually' }))[0]);

    // The individual endpoint — the repair tool — was called for the odd
    // member specifically, not for the group and not for its sibling.
    await waitFor(() =>
      expect(bookingService.transitionState).toHaveBeenCalledWith(
        ALPHA_BOOKING_ID,
        'approved',
        undefined
      )
    );

    // BookingDetail refetched the request, which changed `statusesKey`, which
    // is what makes the group's intersection refetch (Task 9's fix, exercised
    // here through the real wiring rather than by handing the panel new props).
    await waitFor(() =>
      expect(environmentGroupService.groupAllowedTransitions).toHaveBeenCalledTimes(2)
    );

    // And the loop closes: the group can move again, and the divergence
    // notice is gone because there is no longer a divergence.
    expect(await screen.findByRole('button', { name: 'Close Group' })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText(/Members are out of step/i)).not.toBeInTheDocument()
    );
  });
});
