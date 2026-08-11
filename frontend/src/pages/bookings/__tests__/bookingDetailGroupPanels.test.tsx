import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { store } from '../../../store';
import type { BookingResponse } from '../../../types/booking';
import type { BookingRequestResponse, EnvBookingSummary } from '../../../types/bookingRequest';
import { groupBookingsByEnvironmentGroup } from '../BookingDetail';

// Task 9 — group transitions in the UI. This file covers the composition
// BookingDetail owns: splitting a request's bookings into one
// GroupTransitionPanel per distinct group plus the hand-picked remainder,
// which stays in EnvironmentsPanel exactly as before. GroupTransitionPanel's
// own behaviour (buttons from the group endpoint, out-of-step notice, error
// rendering) is covered in
// ../../../components/bookings/__tests__/GroupTransitionPanel.test.tsx —
// not repeated here.

// GroupTransitionPanel and EnvironmentsPanel are mocked down to the props
// BookingDetail passes them, so this file tests the wiring — which bookings
// land in which panel — without needing every service either real child
// component would itself call.
vi.mock('../../../components/bookings/GroupTransitionPanel', () => ({
  default: (props: { groupId: number; groupName: string; bookings: EnvBookingSummary[] }) => (
    <div data-testid={`group-panel-${props.groupId}`}>
      <span data-testid={`group-panel-${props.groupId}-name`}>{props.groupName}</span>
      <span data-testid={`group-panel-${props.groupId}-members`}>
        {props.bookings.map((b) => b.environment_name).join(',')}
      </span>
    </div>
  ),
}));

vi.mock('../../../components/bookings/EnvironmentsPanel', () => ({
  default: (props: { envBookings: EnvBookingSummary[] }) => (
    <div data-testid="environments-panel">
      {props.envBookings.map((b) => b.environment_name).join(',')}
    </div>
  ),
}));

// Irrelevant to this test's concern (which bookings land in which panel) and
// makes its own fetches — mocked to a stub so it doesn't add noise.
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

// Deliberately distinct id ranges from every other fixture file exercising
// this area (GroupTransitionPanel.test.tsx uses request 7301 / group 7401;
// bookingFormGroups.test.tsx uses env 501 / groups 601-602) so a
// wrong-data-source bug cannot pass by numeric coincidence. Booking ids
// 91xx, environment ids 81xx, group ids 60xx, request id 9001.
const REQUEST_ID = 9001;

const TOP_BOOKING_ID = 9101; // the booking this page is mounted for

const ORDER_GROUP_ID = 6011;
const ORDER_GROUP_NAME = 'Order Squad';
const LEDGER_GROUP_ID = 6012;
const LEDGER_GROUP_NAME = 'Ledger Squad';

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

const ORDER_MEMBER_1 = envBooking({
  id: TOP_BOOKING_ID,
  environment_id: 8101,
  environment_name: 'Order Service Test',
  environment_group_id: ORDER_GROUP_ID,
  environment_group_name: ORDER_GROUP_NAME,
});
const ORDER_MEMBER_2 = envBooking({
  id: 9102,
  environment_id: 8102,
  environment_name: 'Order Service DB',
  environment_group_id: ORDER_GROUP_ID,
  environment_group_name: ORDER_GROUP_NAME,
});
const LEDGER_MEMBER_1 = envBooking({
  id: 9103,
  environment_id: 8103,
  environment_name: 'Ledger Primary',
  status: 'approved',
  environment_group_id: LEDGER_GROUP_ID,
  environment_group_name: LEDGER_GROUP_NAME,
});
const LEDGER_MEMBER_2 = envBooking({
  id: 9104,
  environment_id: 8104,
  environment_name: 'Ledger Replica',
  status: 'approved',
  environment_group_id: LEDGER_GROUP_ID,
  environment_group_name: LEDGER_GROUP_NAME,
});
const HAND_PICKED = envBooking({
  id: 9105,
  environment_id: 8105,
  environment_name: 'Adhoc Sandbox',
  status: 'draft',
  environment_group_id: null,
  environment_group_name: null,
});

function makeBooking(): BookingResponse {
  return {
    has_unacknowledged_conflicts: false,
    id: TOP_BOOKING_ID,
    environment_id: 8101,
    environment_name: 'Order Service Test',
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
    agreement_gap: null,
    has_unacknowledged_agreement_gap: false,
    environment_group_id: ORDER_GROUP_ID,
    environment_group_name: ORDER_GROUP_NAME,
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
    protection_level: 'soft',
    custom_fields: null,
    booked_by: 1,
    delegate_user_ids: null,
    rollup_status: 'submitted',
    bookings: [ORDER_MEMBER_1, ORDER_MEMBER_2, LEDGER_MEMBER_1, LEDGER_MEMBER_2, HAND_PICKED],
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

describe('BookingDetail — group panel composition', () => {
  beforeEach(() => {
    vi.mocked(bookingService.getBooking).mockReset().mockResolvedValue(makeBooking());
    vi.mocked(bookingRequestService.get).mockReset().mockResolvedValue(makeRequest());
  });

  it('renders one panel per distinct group on the request, not one merged panel', async () => {
    renderPage();

    await waitFor(() => expect(screen.getByTestId(`group-panel-${ORDER_GROUP_ID}`)).toBeInTheDocument());
    expect(screen.getByTestId(`group-panel-${LEDGER_GROUP_ID}`)).toBeInTheDocument();
    // Exactly two — grouping by `environment_group_id != null` alone (a
    // single grouped/ungrouped split) would either collapse these two
    // distinct groups into one panel or duplicate them; there must be
    // exactly one per distinct group id.
    expect(screen.getAllByTestId(/^group-panel-\d+$/)).toHaveLength(2);

    expect(screen.getByTestId(`group-panel-${ORDER_GROUP_ID}-name`).textContent).toBe(
      ORDER_GROUP_NAME
    );
    expect(screen.getByTestId(`group-panel-${LEDGER_GROUP_ID}-name`).textContent).toBe(
      LEDGER_GROUP_NAME
    );
  });

  it('puts each group panel members only from its own group, not the other', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId(`group-panel-${ORDER_GROUP_ID}`)).toBeInTheDocument());

    const orderMembers = screen.getByTestId(`group-panel-${ORDER_GROUP_ID}-members`).textContent;
    expect(orderMembers).toContain('Order Service Test');
    expect(orderMembers).toContain('Order Service DB');
    expect(orderMembers).not.toContain('Ledger');
    expect(orderMembers).not.toContain('Adhoc Sandbox');

    const ledgerMembers = screen.getByTestId(`group-panel-${LEDGER_GROUP_ID}-members`).textContent;
    expect(ledgerMembers).toContain('Ledger Primary');
    expect(ledgerMembers).toContain('Ledger Replica');
    expect(ledgerMembers).not.toContain('Order Service');
    expect(ledgerMembers).not.toContain('Adhoc Sandbox');
  });

  it('renders the hand-picked booking outside every group panel, in EnvironmentsPanel', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('environments-panel')).toBeInTheDocument());

    const ungrouped = screen.getByTestId('environments-panel').textContent;
    expect(ungrouped).toBe('Adhoc Sandbox');

    // And it must not have leaked into either group panel.
    const orderMembers = screen.getByTestId(`group-panel-${ORDER_GROUP_ID}-members`).textContent;
    const ledgerMembers = screen.getByTestId(`group-panel-${LEDGER_GROUP_ID}-members`).textContent;
    expect(orderMembers).not.toContain('Adhoc Sandbox');
    expect(ledgerMembers).not.toContain('Adhoc Sandbox');
  });
});

describe('groupBookingsByEnvironmentGroup', () => {
  it('splits into one entry per distinct group id, preserving each group members and the ungrouped remainder', () => {
    const result = groupBookingsByEnvironmentGroup([
      ORDER_MEMBER_1,
      LEDGER_MEMBER_1,
      ORDER_MEMBER_2,
      HAND_PICKED,
      LEDGER_MEMBER_2,
    ]);

    expect(result.groups.map((g) => g.groupId).sort()).toEqual(
      [ORDER_GROUP_ID, LEDGER_GROUP_ID].sort()
    );
    const order = result.groups.find((g) => g.groupId === ORDER_GROUP_ID)!;
    expect(order.groupName).toBe(ORDER_GROUP_NAME);
    expect(order.bookings.map((b) => b.id).sort()).toEqual(
      [ORDER_MEMBER_1.id, ORDER_MEMBER_2.id].sort()
    );

    const ledger = result.groups.find((g) => g.groupId === LEDGER_GROUP_ID)!;
    expect(ledger.bookings.map((b) => b.id).sort()).toEqual(
      [LEDGER_MEMBER_1.id, LEDGER_MEMBER_2.id].sort()
    );

    expect(result.ungrouped.map((b) => b.id)).toEqual([HAND_PICKED.id]);
  });

  it('returns no groups and everything ungrouped when no booking belongs to a group', () => {
    const result = groupBookingsByEnvironmentGroup([HAND_PICKED]);
    expect(result.groups).toEqual([]);
    expect(result.ungrouped).toEqual([HAND_PICKED]);
  });
});
