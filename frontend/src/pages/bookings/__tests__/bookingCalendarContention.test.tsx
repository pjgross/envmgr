import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { configureStore } from '@reduxjs/toolkit';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import BookingCalendar, { renderEventContent } from '../BookingCalendar';
import authReducer from '../../../store/authSlice';
import adminReducer from '../../../store/adminSlice';
import apiKeyReducer from '../../../store/apiKeySlice';
import buildReducer from '../../../store/buildSlice';
import tenantAdminReducer from '../../../store/tenantAdminSlice';
import systemReducer from '../../../store/systemSlice';
import environmentReducer from '../../../store/environmentSlice';
import dependencyReducer from '../../../store/dependencySlice';
import deploymentReducer from '../../../store/deploymentSlice';
import bookingRequestReducer from '../../../store/bookingRequestSlice';
import versionReducer from '../../../store/versionSlice';
import customFieldReducer from '../../../store/customFieldSlice';
import topologyReducer from '../../../store/topologySlice';
import bookingLifecycleReducer from '../../../store/bookingLifecycleSlice';
import componentTypeReducer from '../../../store/componentTypeSlice';
import uiReducer from '../../../store/uiSlice';
import changeRequestReducer from '../../../store/changeRequestSlice';
import infrastructureComponentReducer from '../../../store/infrastructureComponentSlice';
import releaseReducer from '../../../store/releaseSlice';
import releaseTemplateReducer from '../../../store/releaseTemplateSlice';
import releaseEventTypeReducer from '../../../store/releaseEventTypeSlice';
import scopeChangeRulesReducer from '../../../store/scopeChangeRulesSlice';
import enterpriseMembershipReducer from '../../../store/enterpriseMembershipSlice';
import raidReducer from '../../../store/raidSlice';
import incidentReducer from '../../../store/incidentSlice';
import projectReducer from '../../../store/projectSlice';
import type { BookingResponse } from '../../../types/booking';

// Task 7 (B6): contention markers on the booking calendar. `contention_state`
// already arrives on every BookingResponse the calendar fetches (Task 4) —
// this covers only the new marker, added through FullCalendar's
// `eventContent` render prop.
//
// jsdom cannot reliably render FullCalendar's own event DOM for anything
// beyond plain text (bookingCalendarProtection.test.tsx already established
// this and tests `bookingToEvent` directly for exactly that reason). The
// marker is a React component (an icon + MUI Typography), not plain text
// folded into `event.title`, so it can't be tested that way either — instead
// `renderEventContent`, the function handed to FullCalendar's `eventContent`
// prop, is exported and exercised directly against a synthetic
// EventContentArg-shaped object, the same technique bookingListContention's
// `renderColumnCell` uses for the DataGrid column FullCalendar's DataGrid
// counterpart can't render past the first columns in jsdom either.

vi.mock('../../../services/bookingService', () => ({
  bookingService: {
    listBookings: vi.fn(),
    getAllowedTransitions: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock('../../../services/projectService', () => ({
  projectService: {
    listProjects: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

import { bookingService } from '../../../services/bookingService';

const mockListBookings = vi.mocked(bookingService.listBookings);

function makeBooking(overrides: Partial<BookingResponse>): BookingResponse {
  return {
    id: 0,
    environment_id: 1,
    environment_name: null,
    project_name: '',
    project_id: null,
    project_name_link: null,
    booked_by: 1,
    booked_by_username: null,
    start_date: '2026-08-01T00:00:00Z',
    end_date: '2026-08-02T00:00:00Z',
    booking_type_id: 1,
    exclusive_use: false,
    status: 'approved',
    notes: null,
    recurrence_rule: null,
    recurrence_parent_id: null,
    release_id: null,
    test_phase_id: null,
    context_tag: 'none',
    custom_fields: null,
    tenant_id: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    has_unacknowledged_conflicts: false,
    agreement_gap: null,
    has_unacknowledged_agreement_gap: false,
    environment_group_id: null,
    environment_group_name: null,
    contention_state: null,
    ...overrides,
  } as BookingResponse;
}

// Minimal shape of the one FullCalendar hands `eventContent`: a `.event`
// with `.title` and `.extendedProps`. Only the fields `renderEventContent`
// actually reads are supplied — a wider fake would hide a dependency on a
// field the real FullCalendar might not always populate.
function makeArg(booking: BookingResponse) {
  return {
    event: {
      title: booking.project_name,
      extendedProps: { booking },
    },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any;
}

function renderCalendar() {
  const testStore = configureStore({
    reducer: {
      auth: authReducer,
      ui: uiReducer,
      admin: adminReducer,
      apiKey: apiKeyReducer,
      build: buildReducer,
      tenantAdmin: tenantAdminReducer,
      system: systemReducer,
      environment: environmentReducer,
      dependency: dependencyReducer,
      deployment: deploymentReducer,
      booking: (state = { bookings: [], loading: false, error: null }) => state,
      bookingRequest: bookingRequestReducer,
      version: versionReducer,
      customField: customFieldReducer,
      topology: topologyReducer,
      bookingLifecycle: bookingLifecycleReducer,
      componentType: componentTypeReducer,
      changeRequest: changeRequestReducer,
      infrastructureComponent: infrastructureComponentReducer,
      release: releaseReducer,
      releaseTemplate: releaseTemplateReducer,
      releaseEventType: releaseEventTypeReducer,
      scopeChangeRules: scopeChangeRulesReducer,
      enterpriseMembership: enterpriseMembershipReducer,
      raid: raidReducer,
      incident: incidentReducer,
      project: projectReducer,
    },
  });

  return render(
    <Provider store={testStore}>
      <MemoryRouter>
        <BookingCalendar />
      </MemoryRouter>
    </Provider>
  );
}

describe('renderEventContent — the marker function handed to FullCalendar', () => {
  it('renders the contention marker for a contended booking', () => {
    const booking = makeBooking({ id: 1, project_name: 'Release 24.4', contention_state: 'unowned' });
    const { container } = render(<>{renderEventContent(makeArg(booking))}</>);

    expect(screen.getByTestId('contention-marker')).toBeInTheDocument();
    expect(container.textContent).toMatch(/needs escalating/i);
  });

  it('renders NOTHING for the common case — no contention', () => {
    // Not an empty marker: absence of the marker entirely. The common case,
    // not an edge case.
    const booking = makeBooking({ id: 2, project_name: 'Release 24.4', contention_state: null });
    render(<>{renderEventContent(makeArg(booking))}</>);

    expect(screen.queryByTestId('contention-marker')).not.toBeInTheDocument();
  });

  it('distinguishes all three contention states', () => {
    const labels: Record<string, RegExp> = {
      unowned: /needs escalating/i,
      owned: /awaiting a decision/i,
      decided: /decided/i,
    };
    (['unowned', 'owned', 'decided'] as const).forEach((state) => {
      const booking = makeBooking({ id: 10, project_name: 'X', contention_state: state });
      const { container, unmount } = render(<>{renderEventContent(makeArg(booking))}</>);
      expect(container.textContent).toMatch(labels[state]);
      unmount();
    });
  });

  it('still renders the event title alongside the marker', () => {
    // eventContent REPLACES FullCalendar's own title rendering — this
    // guards against a marker that swallows the title text.
    const booking = makeBooking({ id: 3, project_name: 'Release 9.1', contention_state: 'owned' });
    const { container } = render(<>{renderEventContent(makeArg(booking))}</>);
    expect(container.textContent).toContain('Release 9.1');
  });
});

describe('BookingCalendar — clicking a contended event still opens its detail', () => {
  it('opens the booking detail drawer on click, unchanged by the marker', async () => {
    mockListBookings.mockResolvedValue({
      rows: [
        makeBooking({
          id: 42,
          project_name: 'Contended Release',
          start_date: '2026-08-03T00:00:00Z',
          end_date: '2026-08-04T00:00:00Z',
          status: 'approved',
          environment_id: 1,
          contention_state: 'unowned',
        }),
      ],
      total: 1,
    });

    renderCalendar();

    const event = await screen.findByText(/Contended Release/);
    await userEvent.click(event);

    // The drawer renders "View full details" only once a booking is
    // selected via handleEventClick — this is the existing navigation path,
    // unchanged.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /view full details/i })).toBeInTheDocument()
    );
  });
});
