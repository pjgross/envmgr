import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { store } from '../../../store';
import type { BookingResponse } from '../../../types/booking';
import type { BookingRequestResponse, EnvBookingSummary } from '../../../types/bookingRequest';

// Task 9 review finding #2 — a regression this diff introduced.
// `BookingDetail` used to pass `bookingRequest.bookings` straight through to
// `EnvironmentsPanel` (a stable, state-held reference). The group-panel split
// replaced that with `groupBookingsByEnvironmentGroup(...)` called directly
// in the render body, which builds brand new `groups`/`ungrouped` arrays
// every render. `EnvironmentsPanel`'s own effect
// (../../../components/bookings/EnvironmentsPanel.tsx:43-57) depends on
// `[envBookings]` BY IDENTITY, so every unrelated re-render of BookingDetail
// (e.g. typing into the Add-Environment dialog) refetched every hand-picked
// booking's allowed transitions again. This file exercises the REAL
// EnvironmentsPanel (not mocked) to prove the fetch count stays put across
// an unrelated local state change.
//
// GroupTransitionPanel is mocked out — its own refetch behaviour is covered
// in ../../../components/bookings/__tests__/GroupTransitionPanel.test.tsx —
// and the fixture below has no grouped bookings at all, so it never renders.
vi.mock('../../../components/bookings/GroupTransitionPanel', () => ({
  default: () => <div data-testid="group-panel-stub" />,
}));

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
  bookingRequestService: {
    get: vi.fn(),
  },
}));
vi.mock('../../../services/bookingLifecycleService', () => ({
  bookingLifecycleService: {
    listBookingTypes: vi.fn().mockResolvedValue([]),
    listTemplates: vi.fn().mockResolvedValue([]),
  },
}));
vi.mock('../../../services/customFieldService', () => ({
  customFieldService: {
    listDefinitions: vi.fn().mockResolvedValue([]),
  },
}));
vi.mock('../../../services/environmentService', () => ({
  environmentService: {
    listEnvironments: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

import { bookingService } from '../../../services/bookingService';
import { bookingRequestService } from '../../../services/bookingRequestService';
import BookingDetail from '../BookingDetail';

// Distinct id range from every other fixture file in this area
// (GroupTransitionPanel.test.tsx: request 7301/group 7401; bookingFormGroups:
// env 501/groups 601-602; bookingDetailGroupPanels: request 9001, ids 91xx/
// 81xx/60xx) so a wrong-data-source bug can't pass by coincidence.
const REQUEST_ID = 9501;
const TOP_BOOKING_ID = 9601;
const ENV_ID = 8601;

function envBooking(overrides: Partial<EnvBookingSummary>): EnvBookingSummary {
  return {
    id: 0,
    environment_id: 0,
    environment_name: null,
    project_name: 'Regression sweep',
    start_date: '2026-08-10T09:00:00Z',
    end_date: '2026-08-11T09:00:00Z',
    status: 'submitted',
    environment_group_id: null,
    environment_group_name: null,
    ...overrides,
  };
}

// A single hand-picked booking, no groups — the booking this page is mounted
// for IS the sole ungrouped member, so its allowed transitions get fetched
// twice on mount (once by BookingDetail's own top-level load, once by
// EnvironmentsPanel's per-booking preload). That is expected and stable; the
// point under test is that this count must NOT climb further on an unrelated
// re-render.
const SOLO_BOOKING = envBooking({
  id: TOP_BOOKING_ID,
  environment_id: ENV_ID,
  environment_name: 'Solo Env',
});

function makeBooking(): BookingResponse {
  return {
    id: TOP_BOOKING_ID,
    environment_id: ENV_ID,
    environment_name: 'Solo Env',
    project_name: 'Checkout release',
    project_id: null,
    project_name_link: null,
    booked_by: 1,
    booked_by_username: 'alice',
    start_date: '2026-08-10T09:00:00Z',
    end_date: '2026-08-11T09:00:00Z',
    booking_type_id: 5,
    exclusive_use: false,
    status: 'submitted',
    notes: null,
    recurrence_rule: null,
    recurrence_parent_id: null,
    release_id: null,
    test_phase_id: null,
    context_tag: 'none',
    custom_fields: null,
    environment_group_id: null,
    environment_group_name: null,
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
  };
}

function makeRequest(): BookingRequestResponse {
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
    rollup_status: 'submitted',
    bookings: [SOLO_BOOKING],
  };
}

function renderPage() {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[`/bookings/${TOP_BOOKING_ID}`]}>
        <Routes>
          <Route path="/bookings/:id" element={<BookingDetail />} />
        </Routes>
      </MemoryRouter>
    </Provider>
  );
}

describe('BookingDetail — ungrouped bookings array identity', () => {
  beforeEach(() => {
    vi.mocked(bookingService.getBooking).mockReset().mockResolvedValue(makeBooking());
    vi.mocked(bookingService.getAllowedTransitions).mockReset().mockResolvedValue([]);
    vi.mocked(bookingRequestService.get).mockReset().mockResolvedValue(makeRequest());
  });

  it('does not refetch a hand-picked booking\'s allowed transitions on an unrelated local state change', async () => {
    renderPage();

    // Wait for the page (and EnvironmentsPanel's own preload effect) to
    // settle. "Solo Env" renders twice (the details box and the
    // EnvironmentsPanel row), so anchor on the Add Environment button
    // instead, which only exists once EnvironmentsPanel has mounted.
    await screen.findByRole('button', { name: /add environment/i });
    const settledCount = await waitFor(() => {
      const count = vi.mocked(bookingService.getAllowedTransitions).mock.calls.length;
      expect(count).toBeGreaterThan(0);
      return count;
    });

    // Trigger a local state change that never touches `bookingRequest`:
    // open the Add-Environment dialog, then type into its Start Date field —
    // exactly the reproduction from the review (1 keystroke took the call
    // count from 1 to 4 for a single booking).
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /add environment/i }));
    const startDateField = await screen.findByLabelText(/start date/i);
    await user.type(startDateField, '2026-09-01');

    // Give any wrongful refetch a chance to fire before asserting it didn't.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(vi.mocked(bookingService.getAllowedTransitions).mock.calls.length).toBe(settledCount);
  });
});
