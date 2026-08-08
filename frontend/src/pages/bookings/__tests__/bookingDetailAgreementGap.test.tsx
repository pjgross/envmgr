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
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
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
    updateStandardFields: vi.fn(),
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
// The ack's author, as the SERVER reports them. Deliberately nobody the page
// could otherwise know about: no user is signed into the store in this file, and
// neither name matches the booking's `booked_by_username` ('alice'). So a name
// on screen can only have come off the response.
//
// Task 6b deleted the `currentUserId`/`currentUsername` props this file used to
// seed `setCredentials` for. The name now travels with the row, the way
// `owner_username` and `ReleaseSystemRead.system_name` do — one source, so
// nothing can render a locally-guessed name beside a server-supplied one.
const ACK_USER_ID = 4401;
const ACK_USERNAME = 'rmanager';
const EARLIER_ACK_USER_ID = 4404;
const EARLIER_ACK_USERNAME = 'governance-lead';
const EARLIER_ACK_AT = '2026-07-01T09:15:00Z';
/** The ack a previous session left behind, as `GET /bookings/{id}` reports it. */
const EARLIER_ACK = {
  notes: 'accepted by the programme board',
  acknowledged_by: EARLIER_ACK_USER_ID,
  acknowledged_by_username: EARLIER_ACK_USERNAME,
  acknowledged_at: EARLIER_ACK_AT,
};
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
    // The ack row as `GET /bookings/{id}` reports it — null while nobody has
    // accepted the gap. Detail-only: the list deliberately omits it.
    agreement_gap_ack: null,
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
  // The server's answer to the ack, carrying the author's NAME — the only
  // source of it. Nothing signs a user into the store in this file, on purpose.
  vi.mocked(agreementGapService.ackGap).mockReset().mockResolvedValue({
    notes: null,
    acknowledged_by: ACK_USER_ID,
    acknowledged_by_username: ACK_USERNAME,
    acknowledged_at: '2026-08-08T10:30:00Z',
  });
});

describe('BookingDetail — the usage-agreement gap is on the page', () => {
  it("shows the booking's gap message", async () => {
    renderPage();
    expect(await screen.findByText(GAP)).toBeInTheDocument();
  });

  it('names who acknowledged a gap in an EARLIER session, and when, and offers no Acknowledge control', async () => {
    // TWO SEAMS IN ONE TEST, both of the shape that has already regressed here
    // with a green suite:
    //
    //  - `hasUnacknowledgedGap` must come from the booking, not a constant:
    //    hardcoded `true` and a gap accepted last week re-offers the control
    //    forever and never shows the acknowledged line at all.
    //  - `gapAck` must be PASSED DOWN. Fetching it and forgetting to hand it to
    //    the panel is Task 6's F1 on a new prop — it leaves the panel falling
    //    back to "This gap has been acknowledged.", which is exactly what this
    //    file asserted before task 6b and would have kept asserting happily.
    //
    // Nothing in-session sets an ack here: no click, no PUT. The name can only
    // have arrived on the response.
    vi.mocked(bookingService.getBooking).mockResolvedValue(
      makeBooking({
        has_unacknowledged_agreement_gap: false,
        agreement_gap_ack: EARLIER_ACK,
      })
    );
    renderPage();

    // Acknowledging is not resolving: the gap is still on the page.
    expect(await screen.findByText(GAP)).toBeInTheDocument();
    const ackLine = await screen.findByTestId('agreement-gap-ack');
    // Who…
    expect(ackLine).toHaveTextContent(new RegExp(`Acknowledged by ${EARLIER_ACK_USERNAME}`, 'i'));
    // …and when.
    expect(ackLine).toHaveTextContent(
      new RegExp(new Date(EARLIER_ACK_AT).toLocaleString().replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    );
    // By name, never `#N`, and never the nameless fallback when a name exists.
    expect(ackLine.textContent).not.toContain(String(EARLIER_ACK_USER_ID));
    expect(ackLine.textContent).not.toMatch(/has been acknowledged/i);
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

  it("names the ack's author from the SERVER's answer — who AND when", async () => {
    // The in-session half of the same rule. The name comes off the PUT's
    // response and nowhere else: the store holds no user at all in this file,
    // and `ACK_USERNAME` is not the booking's `booked_by_username`, so a page
    // that fell back to either would print no name or the wrong one.
    //
    // (Before task 6b this test seeded `setCredentials` and proved the name came
    // from `state.auth.user`. That seed is now gone rather than left as
    // decoration: with the props deleted it would have guarded nothing while
    // still claiming to.)
    const user = userEvent.setup();
    renderPage();

    await screen.findByText(GAP);
    await user.click(screen.getByRole('button', { name: /^Acknowledge$/ }));

    const ackLine = await screen.findByTestId('agreement-gap-ack');
    expect(ackLine).toHaveTextContent(new RegExp(`Acknowledged by ${ACK_USERNAME}`, 'i'));
    expect(ackLine.textContent).toMatch(/2026/);
    // By name, never `#N` — the ack row's `acknowledged_by` is a user id.
    expect(ackLine.textContent).not.toContain(String(ACK_USER_ID));
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

describe('BookingDetail — an unrelated save must not drop the acknowledgement', () => {
  it("keeps the earlier session's acknowledger on the page after an env-override save", async () => {
    // THE JOIN, NOT THE ENDS. Every other ack assertion in this file is made
    // after the initial load or after the ack PUT; nothing asserted that a
    // booking already displaying "Acknowledged by X" still displays it once
    // page state is REPLACED by an unrelated save. That absence is precisely
    // how review finding I1 shipped — the same shape as task 6's F1.
    const user = userEvent.setup();

    // The page opens on a gap somebody accepted in an earlier session.
    vi.mocked(bookingService.getBooking).mockResolvedValue(
      makeBooking({ has_unacknowledged_agreement_gap: false, agreement_gap_ack: EARLIER_ACK })
    );
    // What `PATCH /bookings/{id}/standard-fields` really answers: a
    // BookingResponse that is NOT the detail read, so `agreement_gap_ack` is
    // present and null — the wire always sends the key. Routing that straight
    // into `setBooking` degrades the ack line to the nameless fallback, and
    // "who and when" — the whole point of task 6b — vanishes until a reload.
    vi.mocked(bookingService.updateStandardFields).mockResolvedValue(
      makeBooking({
        has_unacknowledged_agreement_gap: false,
        agreement_gap_ack: null,
        start_date: '2026-08-12T09:00:00Z',
      })
    );
    renderPage();

    const before = await screen.findByTestId('agreement-gap-ack');
    expect(before).toHaveTextContent(new RegExp(`Acknowledged by ${EARLIER_ACK_USERNAME}`, 'i'));

    await user.click(screen.getByRole('button', { name: /Edit dates/i }));
    await user.click(await screen.findByRole('button', { name: /^Save$/ }));
    await waitFor(() => expect(bookingService.updateStandardFields).toHaveBeenCalled());

    // Still named, and still by name.
    await waitFor(() =>
      expect(screen.getByTestId('agreement-gap-ack')).toHaveTextContent(
        new RegExp(`Acknowledged by ${EARLIER_ACK_USERNAME}`, 'i')
      )
    );
    const after = screen.getByTestId('agreement-gap-ack');
    expect(after.textContent).not.toMatch(/has been acknowledged/i);
    expect(after.textContent).not.toContain(String(EARLIER_ACK_USER_ID));
    // …and the gap is still on the page: acknowledging is not resolving, and a
    // date edit does not resolve it either.
    expect(screen.getByText(GAP)).toBeInTheDocument();
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
    //
    // The ack row is real, not null: `has_unacknowledged_agreement_gap: false`
    // with no ack is a state `GET /bookings/{id}` cannot produce (an
    // acknowledged gap HAS a row — see the backend's
    // `test_the_ack_survives_the_gap_closing…`), and a fixture describing an
    // impossible state is what R1 was rewritten to stop. The assertions below
    // are about transition controls and are indifferent to it either way.
    vi.mocked(bookingService.getBooking).mockResolvedValue(
      makeBooking({ has_unacknowledged_agreement_gap: false, agreement_gap_ack: EARLIER_ACK })
    );
    vi.mocked(bookingService.getAllowedTransitions).mockResolvedValue([SUBMIT]);
    renderPage();

    expect(await screen.findByText(GAP)).toBeInTheDocument();
    const submit = await screen.findByRole('button', { name: SUBMIT.label });
    expect(submit).toBeEnabled();
  });
});
