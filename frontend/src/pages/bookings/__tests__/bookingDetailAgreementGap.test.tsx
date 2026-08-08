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
    acknowledged_by: 1,
    acknowledged_at: '2026-08-08T10:30:00Z',
  });
});

describe('BookingDetail — the usage-agreement gap is on the page', () => {
  it("shows the booking's gap message", async () => {
    renderPage();
    expect(await screen.findByText(GAP)).toBeInTheDocument();
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
