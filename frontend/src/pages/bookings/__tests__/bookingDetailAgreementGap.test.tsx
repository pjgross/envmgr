/**
 * The usage-agreement gap, end to end, with the REAL `AgreementGapPanel`
 * mounted inside `BookingDetail`.
 *
 * WHY THIS FILE EXISTS: on A2 both ends of a seam were tested and the join was
 * not — deleting `onMemberTransition={handleMemberTransition}` from
 * BookingDetail left all 43 frontend tests green while the repair path
 * regressed in full. `AgreementGapPanel.test.tsx` hands the panel its props by
 * hand; nothing there would notice if BookingDetail stopped rendering it, or
 * stopped passing it the booking's gap, or stopped refetching after an ack.
 * So this file mocks the leaf services and NOTHING of the panel.
 *
 * A3 WARNS, IT NEVER BLOCKS: the assertions below check that the warning is
 * visible and that acknowledging is recorded — never that anything is
 * prevented, and never that the gap disappears once acknowledged.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import { logout, setCredentials } from '../../../store/authSlice';
import type { BookingResponse } from '../../../types/booking';
import type { AllowedTransition } from '../../../types/bookingLifecycle';

// Makes its own fetches and is irrelevant to the gap — stubbed so this file's
// failures are about the wiring under test.
vi.mock('../../../components/bookings/ConflictsPanel', () => ({
  default: () => <div data-testid="conflicts-panel" />,
}));

vi.mock('../../../services/bookingService', () => ({
  bookingService: {
    getBooking: vi.fn(),
    getAllowedTransitions: vi.fn().mockResolvedValue([]),
    getHistory: vi.fn().mockResolvedValue([]),
    transitionState: vi.fn(),
  },
}));
vi.mock('../../../services/agreementGapService', () => ({
  agreementGapService: { ackGap: vi.fn() },
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

import { bookingService } from '../../../services/bookingService';
import { agreementGapService } from '../../../services/agreementGapService';
import { bookingRequestService } from '../../../services/bookingRequestService';
import BookingDetail from '../BookingDetail';

// Distinct from every other fixture in this directory (repair path uses 96xx /
// request 9501) so a wrong-data-source bug cannot pass by coincidence.
const BOOKING_ID = 9701;
const ENV_ID = 8701;
// The signed-in user, seeded into the REAL store below. Deliberately not the
// booking's `booked_by`/`booked_by_username` (1/'alice'): the ack line must be
// shown to come from `state.auth.user`, not from a field that happens to sit on
// the booking. `acknowledged_by` on the ack mock matches this id, because the
// backend always records the caller.
const CURRENT_USER_ID = 4401;
const CURRENT_USERNAME = 'rmanager';
const GAP =
  "Mortgage Replatform's booking falls outside its agreed window for Staging (1 Jan 2026 – 30 Jun 2026)";

function makeBooking(overrides: Partial<BookingResponse> = {}): BookingResponse {
  return {
    id: BOOKING_ID,
    environment_id: ENV_ID,
    environment_name: 'Staging',
    project_name: 'Regression sweep',
    project_id: 31,
    project_name_link: 'Mortgage Replatform',
    booked_by: 1,
    booked_by_username: 'alice',
    start_date: '2026-08-10T09:00:00Z',
    end_date: '2026-08-11T09:00:00Z',
    booking_type_id: 5,
    exclusive_use: false,
    status: 'draft',
    notes: null,
    recurrence_rule: null,
    recurrence_parent_id: null,
    release_id: null,
    test_phase_id: null,
    context_tag: 'none',
    custom_fields: null,
    agreement_gap: GAP,
    has_unacknowledged_agreement_gap: true,
    environment_group_id: null,
    environment_group_name: null,
    tenant_id: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    booking_request_id: null,
    ...overrides,
  } as BookingResponse;
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

beforeEach(() => {
  vi.mocked(bookingService.getBooking).mockReset().mockResolvedValue(makeBooking());
  vi.mocked(bookingService.getAllowedTransitions).mockReset().mockResolvedValue([]);
  vi.mocked(bookingService.getHistory).mockReset().mockResolvedValue([]);
  vi.mocked(bookingRequestService.get).mockReset();
  vi.mocked(agreementGapService.ackGap).mockReset().mockResolvedValue({
    notes: null,
    acknowledged_by: CURRENT_USER_ID,
    acknowledged_at: '2026-08-08T10:30:00Z',
  });
  // The page reads `state.auth.user` and passes it to the panel; without a
  // signed-in user in the store no acknowledgement could ever carry a name.
  store.dispatch(
    setCredentials({
      user: {
        id: CURRENT_USER_ID,
        username: CURRENT_USERNAME,
        email: 'rmanager@example.com',
        role: 'Release Manager',
        tenant_id: 1,
        is_master_admin: false,
      },
      token: 'test-token',
    })
  );
});

afterEach(() => {
  // The real store is shared by every test in this file.
  store.dispatch(logout());
});

describe('BookingDetail — the usage-agreement gap is on the page', () => {
  it("shows the booking's gap message", async () => {
    renderPage();
    expect(await screen.findByText(GAP)).toBeInTheDocument();
  });

  it('shows a gap acknowledged in an EARLIER session as acknowledged, and offers no Acknowledge control', async () => {
    // The page's `hasUnacknowledgedGap` prop must come from the booking, not
    // from a constant: hardcoding it `true` leaves every other test in this
    // directory green while a booking whose gap was acknowledged in a previous
    // session re-offers the control forever and never shows the acknowledged
    // line at all. Nothing in-session sets `ack` here — the acknowledged state
    // can only come off the response.
    vi.mocked(bookingService.getBooking).mockResolvedValue(
      makeBooking({ has_unacknowledged_agreement_gap: false })
    );
    renderPage();

    // Acknowledging is not resolving: the gap is still on the page.
    expect(await screen.findByText(GAP)).toBeInTheDocument();
    expect(await screen.findByTestId('agreement-gap-ack')).toHaveTextContent(
      /has been acknowledged/i
    );
    expect(screen.queryByRole('button', { name: /^Acknowledge$/ })).not.toBeInTheDocument();
  });

  it('renders no gap panel for a booking that has none', async () => {
    vi.mocked(bookingService.getBooking).mockResolvedValue(
      makeBooking({ agreement_gap: null, has_unacknowledged_agreement_gap: false })
    );
    renderPage();
    // The page itself has rendered — the environment name is on it — and no
    // gap copy is anywhere near it.
    expect(await screen.findByText('Staging')).toBeInTheDocument();
    expect(screen.queryByText(/usage agreement/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Acknowledge/i })).not.toBeInTheDocument();
  });
});

describe('BookingDetail — acknowledging from the page', () => {
  it('acknowledges this booking, refetches it, and STILL shows the gap afterwards', async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText(GAP);
    const initialFetches = vi.mocked(bookingService.getBooking).mock.calls.length;

    // What the server says once the ack is recorded: the gap is unchanged —
    // it is computed from usage_agreement, and acknowledging is not resolving.
    vi.mocked(bookingService.getBooking).mockResolvedValue(
      makeBooking({ has_unacknowledged_agreement_gap: false })
    );

    await user.click(screen.getByRole('button', { name: /Acknowledge/i }));

    await waitFor(() => expect(agreementGapService.ackGap).toHaveBeenCalledWith(BOOKING_ID, null));
    // The page refetched the booking — the wiring, not just the panel.
    await waitFor(() =>
      expect(vi.mocked(bookingService.getBooking).mock.calls.length).toBeGreaterThan(initialFetches)
    );

    // Second render, from freshly-fetched props: the warning is still there,
    // it is simply no longer unacknowledged.
    expect(await screen.findByText(GAP)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /Acknowledge/i })).not.toBeInTheDocument()
    );
  });

  it('names the signed-in user on the acknowledgement it just recorded — who AND when', async () => {
    // Guards the `currentUserId`/`currentUsername` props at the page seam:
    // pass them as `null` (an auth selector dropped in a refactor) and every
    // acknowledgement silently degrades to "Acknowledged on <date>" — the
    // brief's "who and when" reduced to "when" on the only page that can
    // satisfy it. No other page test asserts a username appears.
    const user = userEvent.setup();
    renderPage();

    await screen.findByText(GAP);
    await user.click(screen.getByRole('button', { name: /^Acknowledge$/ }));

    const ackLine = await screen.findByTestId('agreement-gap-ack');
    expect(ackLine).toHaveTextContent(new RegExp(`Acknowledged by ${CURRENT_USERNAME}`, 'i'));
    // By name, never `#N` — the ack row's `acknowledged_by` is a user id.
    expect(ackLine.textContent).not.toContain(String(CURRENT_USER_ID));
  });

  it("shows the server's reason when the ack is refused, and nothing else on the page breaks", async () => {
    const user = userEvent.setup();
    vi.mocked(agreementGapService.ackGap).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 404',
      response: { status: 404, data: { detail: 'Booking not found' } },
    });
    renderPage();

    await screen.findByText(GAP);
    await user.click(screen.getByRole('button', { name: /Acknowledge/i }));

    expect(await screen.findByText('Booking not found')).toBeInTheDocument();
    expect(screen.queryByText(/Request failed with status code/)).not.toBeInTheDocument();
    // Still warning, still acknowledgeable — a refused ack blocks nothing.
    expect(screen.getByText(GAP)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Acknowledge/i })).toBeEnabled();
  });
});

describe('BookingDetail — A3 WARNS, IT NEVER BLOCKS', () => {
  // A3's central constraint, asserted on the UI side. The rest of this file's
  // fixture stubs `getAllowedTransitions` to `[]`, so the page under test
  // renders no transition control at all and gating one on the gap would be
  // invisible to the whole directory (verified: the reviewer added
  // `&& !booking.has_unacknowledged_agreement_gap` to the TransitionButtons
  // render condition and all 50 tests in src/pages/bookings still passed).
  // This test therefore supplies a real allowed transition.
  const SUBMIT: AllowedTransition = {
    from_state: 'draft',
    to_state: 'submitted',
    label: 'Submit for approval',
  };

  it('still renders the transition controls, enabled, with an UNACKNOWLEDGED gap on the page', async () => {
    vi.mocked(bookingService.getAllowedTransitions).mockResolvedValue([SUBMIT]);
    renderPage();

    // The gap really is on screen, and really is unacknowledged.
    expect(await screen.findByText(GAP)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Acknowledge$/ })).toBeInTheDocument();

    // …and the booking can still be moved forward. Nothing about the warning
    // hides, disables or intercepts it.
    const submit = await screen.findByRole('button', { name: SUBMIT.label });
    expect(submit).toBeInTheDocument();
    expect(submit).toBeEnabled();
  });

  it('still renders the transition controls, enabled, with an ACKNOWLEDGED gap on the page', async () => {
    // The other half: neither state of the warning may gate the workflow.
    vi.mocked(bookingService.getBooking).mockResolvedValue(
      makeBooking({ has_unacknowledged_agreement_gap: false })
    );
    vi.mocked(bookingService.getAllowedTransitions).mockResolvedValue([SUBMIT]);
    renderPage();

    expect(await screen.findByText(GAP)).toBeInTheDocument();
    const submit = await screen.findByRole('button', { name: SUBMIT.label });
    expect(submit).toBeEnabled();
  });
});
