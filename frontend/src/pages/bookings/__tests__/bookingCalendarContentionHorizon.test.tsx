import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { configureStore } from '@reduxjs/toolkit';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import BookingCalendar from '../BookingCalendar';
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
import contentionForecastReducer from '../../../store/contentionForecastSlice';

/**
 * Task 8 (B6) — THE INDEPENDENCE TEST, proved at the real integration point
 * rather than against ContentionHorizon in isolation: this mounts the actual
 * `<BookingCalendar />` page (with the horizon summary Task 8 puts on it) and
 * drives FullCalendar's OWN "Next month" control — the same one a user
 * clicks — rather than anything synthetic.
 *
 * A calendar only ever answers "what's happening in the month I navigated
 * to". The horizon summary's whole reason to exist is a DIFFERENT question —
 * "how much is coming, before I had to ask" — and it only answers that if
 * its fetch is untethered from the visible month. So this asserts the
 * horizon is fetched exactly once — on mount — and navigating months, twice,
 * does not add a second call.
 *
 * `bookingCalendarProtection.test.tsx` already established that jsdom cannot
 * render FullCalendar's own event DOM reliably, which is why that suite and
 * `bookingCalendarContention.test.tsx` both test exported mapping functions
 * directly instead. The header toolbar is different: it is FullCalendar's
 * own plain `<button>` markup (verified empirically — `title="Next month"`,
 * no custom render prop involved), not the custom `eventContent` vdom that
 * motivated that workaround, so driving it directly here is safe.
 */

vi.mock('../../../services/bookingService', () => ({
  bookingService: {
    listBookings: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
    getAllowedTransitions: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock('../../../services/projectService', () => ({
  projectService: {
    listProjects: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

vi.mock('../../../services/contentionForecastService', () => ({
  contentionForecastService: {
    getHorizon: vi.fn().mockResolvedValue({ count: 3, weeks: 6 }),
  },
}));

import { contentionForecastService } from '../../../services/contentionForecastService';

const mockGetHorizon = vi.mocked(contentionForecastService.getHorizon);

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
      contentionForecast: contentionForecastReducer,
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

describe('BookingCalendar — the horizon summary is independent of the month being viewed', () => {
  beforeEach(() => {
    mockGetHorizon.mockClear();
  });

  it('fetches the horizon once on mount and NOT again when the visible month changes', async () => {
    renderCalendar();

    // The summary itself renders once the mount fetch resolves. The count,
    // the "contention(s)" word and "weeks" are separate JSX text nodes, so
    // the container's full textContent is asserted rather than
    // `getByText`, which only ever matches within one node.
    await waitFor(() =>
      expect(screen.getByTestId('contention-horizon').textContent).toMatch(
        /3 contentions in the next 6 weeks/i
      )
    );
    expect(mockGetHorizon).toHaveBeenCalledTimes(1);

    // FullCalendar's own "Next month" control — verified empirically to be a
    // plain <button title="Next month">, not custom render-prop content.
    const nextButton = screen.getByRole('button', { name: /next month/i });
    await userEvent.click(nextButton);
    await userEvent.click(nextButton);

    // Give any (wrongly) wired effect a chance to fire before asserting its
    // absence — a bare synchronous assertion right after the click could
    // pass for the wrong reason if a refetch were scheduled a tick later.
    await waitFor(() => expect(mockGetHorizon).toHaveBeenCalledTimes(1));
    // Held for a further tick: still exactly one call, not creeping up.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(mockGetHorizon).toHaveBeenCalledTimes(1);
  });
});
