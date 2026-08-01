import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
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
import type { BookingResponse } from '../../../types/booking';
import BookingCalendar from '../BookingCalendar';

// No HTTP — this test is about whether the calendar reads its own fetch
// result or the shared booking slice, not about what the server returns.
vi.mock('../../../services/bookingService', () => ({
  bookingService: {
    listBookings: vi.fn(),
    getAllowedTransitions: vi.fn().mockResolvedValue([]),
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
    ...overrides,
  } as BookingResponse;
}

// Real reducers for every slice except `booking`, which deliberately ignores
// every action and always returns the fixed value below — so a regression
// back to `state.booking` is unmissable, while everything BookingCalendar's
// child tree (BookingForm, TransitionButtons, ...) also reads (environment,
// customField, bookingLifecycle, tenantAdmin, auth, ...) gets its normal
// default shape instead of crashing on an incomplete mock store.
function renderCalendarWithSliceBookings(sliceBookings: BookingResponse[]) {
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
      booking: (state = { bookings: sliceBookings, loading: false, error: null }) => state,
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

describe('BookingCalendar own fetch', () => {
  it('renders bookings the shared slice does not contain', async () => {
    // The slice is about to become BookingList's current 25-row page. A
    // calendar showing a month must not be limited to whatever that page
    // holds, so it has to fetch for itself.
    mockListBookings.mockResolvedValue({
      rows: [
        makeBooking({
          id: 91,
          project_name: 'Only via own fetch',
          start_date: '2026-08-03T00:00:00Z',
          end_date: '2026-08-04T00:00:00Z',
          status: 'approved',
          environment_id: 1,
        }),
      ],
      total: 1,
    });

    renderCalendarWithSliceBookings([]); // shared slice deliberately empty

    await waitFor(() => expect(screen.getByText(/Only via own fetch/)).toBeInTheDocument());
  });

  it('does not read the shared booking slice', () => {
    // Guards the regression directly: if the component goes back to the
    // slice, a booking present ONLY there would render.
    mockListBookings.mockResolvedValue({ rows: [], total: 0 });

    renderCalendarWithSliceBookings([
      makeBooking({
        id: 92,
        project_name: 'Only in the slice',
        start_date: '2026-08-05T00:00:00Z',
        end_date: '2026-08-06T00:00:00Z',
        status: 'approved',
        environment_id: 1,
      }),
    ]);

    expect(screen.queryByText(/Only in the slice/)).not.toBeInTheDocument();
  });
});
