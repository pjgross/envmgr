/**
 * A4's verdict and escalation, end to end, with the REAL `ConflictsPanel` and
 * the REAL `ContentionVerdict` mounted inside `BookingDetail`.
 *
 * WHY THIS FILE EXISTS. Every other `BookingDetail` test in this directory
 * stubs `ConflictsPanel` out entirely, so that production component — which
 * fetches `/bookings/{id}/conflicts` for itself — has been unit-test-blind
 * since before this branch. Building A4's UI on top of it without a
 * whole-seam test would repeat A2 exactly: deleting
 * `onMemberTransition={handleMemberTransition}` from BookingDetail left all 43
 * frontend tests green while the repair path regressed in full, because both
 * ENDS were tested and the JOIN was not.
 *
 * So this file mocks the leaf services and NOTHING of either component. Three
 * separate joins are asserted by name below, and each was verified by deleting
 * the wiring and watching the named test fail:
 *
 *   - `ConflictsPanel` renders `ContentionVerdict` at all;
 *   - `BookingDetail` tells the panel which group the SUBJECT booking is in
 *     (`subjectGroupName`) — without it the group note can only ever fire for
 *     the other side;
 *   - escalating reloads the conflicts payload, so the escalation the user just
 *     raised appears without a page refresh.
 *
 * A4 ADVISES; IT NEVER ACTS. Nothing here asserts that anything is prevented.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { store } from '../../../store';
import { setCredentials } from '../../../store/authSlice';
import type { BookingResponse } from '../../../types/booking';
import type { ConflictItem } from '../../../types/conflict';
import type { Contention, Escalation } from '../../../types/contention';

vi.mock('../../../services/bookingService', () => ({
  bookingService: {
    getBooking: vi.fn(),
    getAllowedTransitions: vi.fn().mockResolvedValue([]),
    getHistory: vi.fn().mockResolvedValue([]),
    transitionState: vi.fn(),
    updateStandardFields: vi.fn(),
    getConflicts: vi.fn(),
    getReceivedFeedback: vi.fn().mockResolvedValue([]),
    acknowledgeConflict: vi.fn(),
  },
}));
vi.mock('../../../services/contentionService', () => ({
  contentionService: { escalate: vi.fn(), decide: vi.fn(), list: vi.fn() },
}));
vi.mock('../../../services/bookingRequestService', () => ({
  bookingRequestService: { get: vi.fn() },
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
vi.mock('../../../services/agreementGapService', () => ({
  agreementGapService: { ackGap: vi.fn() },
}));
// The escalate dialog's owner picker, straight through `api`.
vi.mock('../../../services/api', () => ({
  default: { get: vi.fn() },
}));

import api from '../../../services/api';
import { bookingService } from '../../../services/bookingService';
import { bookingRequestService } from '../../../services/bookingRequestService';
import { contentionService } from '../../../services/contentionService';
import BookingDetail from '../BookingDetail';

// Distinct from every other fixture in this directory (agreement gap uses 97xx,
// repair path 96xx) so a wrong-data-source bug cannot pass by coincidence.
const BOOKING_ID = 9801;
const OTHER_ID = 9802;
const REQUEST_ID = 9803;
const ENV_ID = 8801;
const BOOKER_ID = 5501;
const OWNER_ID = 5502;
const OWNER = 'release-manager';

const axiosError = (status: number, detail: string) => ({
  isAxiosError: true,
  name: 'AxiosError',
  message: `Request failed with status code ${status}`,
  response: { status, data: { detail } },
});

function makeBooking(overrides: Partial<BookingResponse> = {}): BookingResponse {
  return {
    id: BOOKING_ID,
    environment_id: ENV_ID,
    environment_name: 'Staging',
    project_name: 'Regression sweep',
    project_id: 31,
    project_name_link: 'Mortgage Replatform',
    booked_by: BOOKER_ID,
    booked_by_username: 'alice',
    start_date: '2026-09-01T09:00:00Z',
    end_date: '2026-09-03T17:00:00Z',
    booking_type_id: 5,
    exclusive_use: false,
    status: 'approved',
    notes: null,
    recurrence_rule: null,
    recurrence_parent_id: null,
    release_id: null,
    test_phase_id: null,
    context_tag: 'none',
    custom_fields: null,
    agreement_gap: null,
    has_unacknowledged_conflicts: true,
    has_unacknowledged_agreement_gap: false,
    agreement_gap_ack: null,
    environment_group_id: null,
    environment_group_name: null,
    tenant_id: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    booking_request_id: REQUEST_ID,
    ...overrides,
  } as BookingResponse;
}

function makeContention(overrides: Partial<Contention> = {}): Contention {
  return {
    outcome: 'ranked',
    winner_booking_id: BOOKING_ID,
    reason: 'the higher-priority project wins',
    escalation: null,
    booking_project_name: 'Mortgage Replatform',
    other_project_name: 'Payments Rebuild',
    ...overrides,
  };
}

function makeEscalation(overrides: Partial<Escalation> = {}): Escalation {
  return {
    id: 9099,
    booking_id: BOOKING_ID,
    other_booking_id: OTHER_ID,
    owner_user_id: OWNER_ID,
    owner_username: OWNER,
    escalated_by: BOOKER_ID,
    escalated_by_username: 'alice',
    respond_by: '2026-09-20T00:00:00Z',
    state: 'open',
    bookings_live: true,
    booking_environment_name: 'Staging',
    booking_project_name: 'Mortgage Replatform',
    other_booking_environment_name: 'Staging',
    other_booking_project_name: 'Payments Rebuild',
    // Neither side is a group booking by default; the group note on this
    // panel is driven by `subjectGroupName` / `environment_group_name`, and
    // these two carry the same fact for the WORKLIST's rows.
    booking_group_name: null,
    other_booking_group_name: null,
    decision_yields_booking_id: null,
    decision_notes: null,
    decided_by: null,
    decided_by_username: null,
    decided_at: null,
    ...overrides,
  };
}

function makeConflict(overrides: Partial<ConflictItem> = {}): ConflictItem {
  return {
    other_booking: {
      id: OTHER_ID,
      environment_id: ENV_ID,
      environment_name: 'Staging',
      project_name: 'Payments smoke test',
      start_date: '2026-09-02T09:00:00Z',
      end_date: '2026-09-04T17:00:00Z',
      status: 'approved',
      has_unacknowledged_conflicts: false,
      agreement_gap: null,
      has_unacknowledged_agreement_gap: false,
      environment_group_id: null,
      environment_group_name: null,
    },
    contention: makeContention(),
    ack: null,
    ...overrides,
  };
}

function renderPage() {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[`/bookings/${BOOKING_ID}`]}>
        <Routes>
          <Route path="/bookings/:id" element={<BookingDetail />} />
        </Routes>
      </MemoryRouter>
    </Provider>
  );
}

/** Sign someone in — `canEscalate` is computed from the store's user. */
function signIn(id: number, role = 'Developer') {
  store.dispatch(
    setCredentials({
      user: {
        id,
        username: `user-${id}`,
        email: `user-${id}@test.com`,
        role,
        tenant_id: 1,
        is_active: true,
        is_master_admin: false,
      } as never,
      token: 'test-token',
    })
  );
}

beforeEach(() => {
  vi.mocked(bookingService.getBooking).mockReset().mockResolvedValue(makeBooking());
  vi.mocked(bookingService.getAllowedTransitions).mockReset().mockResolvedValue([]);
  vi.mocked(bookingService.getHistory).mockReset().mockResolvedValue([]);
  vi.mocked(bookingService.getConflicts).mockReset().mockResolvedValue([makeConflict()]);
  vi.mocked(bookingService.getReceivedFeedback).mockReset().mockResolvedValue([]);
  vi.mocked(contentionService.escalate).mockReset();
  vi.mocked(api.get).mockReset().mockResolvedValue({
    data: [{ id: OWNER_ID, username: OWNER }],
  });
  vi.mocked(bookingRequestService.get).mockReset().mockResolvedValue({
    id: REQUEST_ID,
    tenant_id: 1,
    project_name: 'Regression sweep',
    project_id: 31,
    project_name_link: 'Mortgage Replatform',
    booking_type_id: 5,
    start_date: '2026-09-01T09:00:00Z',
    end_date: '2026-09-03T17:00:00Z',
    notes: null,
    context_tag: 'none',
    exclusive_use_requested: false,
    custom_fields: null,
    booked_by: BOOKER_ID,
    delegate_user_ids: [],
    rollup_status: 'approved',
    bookings: [],
  });
  signIn(BOOKER_ID);
});

describe('the verdict reaches the page', () => {
  it("renders A4's verdict inside the conflicts panel, naming the winning project", async () => {
    // THE WIRING TEST. Deleting <ContentionVerdict/> from ConflictsPanel fails
    // this by name while every other BookingDetail test stays green, because
    // they all stub the panel out.
    renderPage();

    const verdict = await screen.findByTestId('contention-verdict');
    expect(verdict).toHaveTextContent('Mortgage Replatform outranks Payments Rebuild');
  });

  it("names the SUBJECT booking's group when the subject is the one that gives way", async () => {
    // `subjectGroupName` travels BookingDetail → ConflictsPanel →
    // ContentionVerdict. `ConflictItem` carries the group for the OTHER booking
    // only, so without this prop the note can never fire for our own side —
    // and A2 transitions a group atomically, so "this booking gives way" would
    // understate what actually moves.
    vi.mocked(bookingService.getBooking).mockResolvedValue(
      makeBooking({ environment_group_id: 77, environment_group_name: 'Mortgage Suite' })
    );
    vi.mocked(bookingService.getConflicts).mockResolvedValue([
      makeConflict({ contention: makeContention({ winner_booking_id: OTHER_ID }) }),
    ]);
    renderPage();

    expect(await screen.findByTestId('contention-group-note')).toHaveTextContent(
      'Mortgage Suite'
    );
  });

  it('offers no Escalate control to a bystander who owns neither booking', async () => {
    // Mirrors `assert_may_escalate`: the owner or a delegate of either booking,
    // or an Admin. A button that always 403s is worse than no button.
    signIn(999999);
    renderPage();

    await screen.findByTestId('contention-verdict');
    expect(screen.queryByRole('button', { name: /Escalate/i })).not.toBeInTheDocument();
  });

  it('offers the Escalate control to an Admin who owns neither booking', async () => {
    signIn(999999, 'Admin');
    renderPage();

    expect(await screen.findByRole('button', { name: /Escalate/i })).toBeInTheDocument();
  });
});

describe('escalating from the booking page', () => {
  it('records the ask and shows it without a page refresh', async () => {
    const user = userEvent.setup();
    vi.mocked(contentionService.escalate).mockResolvedValue(makeEscalation());
    renderPage();

    await screen.findByTestId('contention-verdict');
    // What the server says once the escalation exists — the SAME payload the
    // panel refetches, so the escalation can only appear if it really reloaded.
    vi.mocked(bookingService.getConflicts).mockResolvedValue([
      makeConflict({ contention: makeContention({ escalation: makeEscalation() }) }),
    ]);

    await user.click(screen.getByRole('button', { name: /Escalate/i }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('combobox', { name: 'Decision owner' }));
    await user.click(await screen.findByRole('option', { name: OWNER }));
    await user.click(within(dialog).getByRole('button', { name: /^Escalate$/i }));

    await waitFor(() =>
      expect(contentionService.escalate).toHaveBeenCalledWith(
        BOOKING_ID,
        OTHER_ID,
        expect.objectContaining({ owner_user_id: OWNER_ID })
      )
    );
    // Second render, from a freshly-fetched payload.
    const panel = await screen.findByTestId('contention-escalation');
    expect(panel).toHaveTextContent(OWNER);
    // …and the verdict is still there. Escalating decides nothing.
    expect(screen.getByTestId('contention-verdict')).toHaveTextContent(
      'Mortgage Replatform outranks Payments Rebuild'
    );
  });

  it("shows the server's refusal, not an HTTP status", async () => {
    const user = userEvent.setup();
    vi.mocked(contentionService.escalate).mockRejectedValue(
      axiosError(403, 'You are not the owner or a delegate of either booking')
    );
    renderPage();

    await screen.findByTestId('contention-verdict');
    await user.click(screen.getByRole('button', { name: /Escalate/i }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('combobox', { name: 'Decision owner' }));
    await user.click(await screen.findByRole('option', { name: OWNER }));
    await user.click(within(dialog).getByRole('button', { name: /^Escalate$/i }));

    expect(
      await screen.findByText('You are not the owner or a delegate of either booking')
    ).toBeInTheDocument();
    expect(screen.queryByText(/Request failed with status code/)).not.toBeInTheDocument();
  });
});

describe('A4 advises; it never acts', () => {
  it('leaves the acknowledgement controls the conflicts panel already had', async () => {
    // The verdict is an ADDITION to the panel, not a replacement for it: the
    // conflict feedback A3 and the original conflicts work put there must still
    // be usable beside it.
    renderPage();

    await screen.findByTestId('contention-verdict');
    expect(screen.getByLabelText(/Willing to share/i)).toBeEnabled();
    expect(screen.getByRole('button', { name: /^Save$/i })).toBeEnabled();
  });
});
