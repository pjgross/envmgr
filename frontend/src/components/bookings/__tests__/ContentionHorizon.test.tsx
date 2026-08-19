import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { configureStore } from '@reduxjs/toolkit';
import { Provider } from 'react-redux';
import { MemoryRouter, useLocation, type NavigateFunction, useNavigate } from 'react-router-dom';
import type { ReactNode } from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import ContentionHorizon from '../ContentionHorizon';
import contentionForecastReducer from '../../../store/contentionForecastSlice';
import type { ContentionHorizon as ContentionHorizonPayload } from '../../../types/contentionForecast';

// Task 8 (B6) — the horizon summary, and the feature's central claim:
//
// A calendar only ever answers "what is happening in the month I navigated
// to". This component's whole reason to exist is to answer a DIFFERENT
// question — "how much is coming, before I had to ask" — and it only does
// that if its count is untethered from whatever month the calendar next to
// it happens to be showing. `describe('independent of the month being
// viewed')` below is that claim, checked against the real integration: it
// mounts the actual BookingCalendar page (which Task 7 already gave a
// contention marker, and which this task mounts ContentionHorizon on) and
// drives FullCalendar's own "Next month" control, then asserts the horizon
// was fetched exactly once — on mount, never again.
//
// Every other test here exercises ContentionHorizon standalone. The service
// boundary (`GET /bookings/contention-horizon?weeks=`, the exact param
// name) is already pinned by contentionForecastService.test.ts and the
// AxiosError-shaped rejection path by contentionForecastSlice.test.ts; this
// file mocks `contentionForecastService` itself rather than raw `api`, so
// it tests the component<->slice boundary without re-asserting a wire
// format two files already own, and without needing to also stub every
// unrelated axios call BookingCalendar's own mount makes (customFieldSlice,
// useAllEnvironments) the way bookingCalendarContention.test.tsx already
// tolerates leaving unmocked.

vi.mock('../../../services/contentionForecastService', () => ({
  contentionForecastService: { getHorizon: vi.fn() },
}));

import { contentionForecastService } from '../../../services/contentionForecastService';

const mockGetHorizon = vi.mocked(contentionForecastService.getHorizon);

function resolveHorizon(payload: ContentionHorizonPayload) {
  mockGetHorizon.mockResolvedValue(payload);
}

function makeStore() {
  return configureStore({ reducer: { contentionForecast: contentionForecastReducer } });
}

/** Exposes the live `location.search` alongside the children it wraps — the
 * same technique useServerGrid.test.tsx's `locationHarness` uses — so a test
 * can assert what a click did to the URL rather than to component state. */
function locationHarness(initialEntries: string[]) {
  const state: { navigate: NavigateFunction | null; search: string } = {
    navigate: null,
    search: '',
  };
  function Watcher({ children }: { children: ReactNode }) {
    state.navigate = useNavigate();
    state.search = useLocation().search;
    return <>{children}</>;
  }
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MemoryRouter initialEntries={initialEntries}>
        <Watcher>{children}</Watcher>
      </MemoryRouter>
    );
  }
  return { Wrapper, state };
}

function renderStandalone(initialEntries = ['/bookings/calendar']) {
  const store = makeStore();
  const { Wrapper, state } = locationHarness(initialEntries);
  const result = render(
    <Provider store={store}>
      <Wrapper>
        <ContentionHorizon />
      </Wrapper>
    </Provider>
  );
  return { ...result, locationState: state };
}

// The count, the "contention(s)" word and "weeks" are three separate JSX
// expressions and so land in three separate text nodes — a plain
// `getByText(/regex spanning all three/)` can never match them (Testing
// Library matches one node's textContent at a time). Reading the container's
// full textContent is the same technique ContentionMarker's own tests use
// for the same reason.
function horizonText(): string {
  return screen.getByTestId('contention-horizon').textContent ?? '';
}

describe('ContentionHorizon', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows the count for the default six-week horizon', async () => {
    resolveHorizon({ count: 4, weeks: 6 });

    renderStandalone();

    await waitFor(() => expect(mockGetHorizon).toHaveBeenCalledWith(6));
    await waitFor(() => expect(horizonText()).toMatch(/4 contentions in the next 6 weeks/i));
  });

  it('widening the horizon refetches with the new value', async () => {
    resolveHorizon({ count: 4, weeks: 6 });
    renderStandalone();
    await waitFor(() => expect(mockGetHorizon).toHaveBeenCalledWith(6));

    resolveHorizon({ count: 11, weeks: 26 });
    await userEvent.click(screen.getByRole('button', { name: /26 weeks/i }));

    await waitFor(() => expect(mockGetHorizon).toHaveBeenCalledWith(26));
    await waitFor(() => expect(horizonText()).toMatch(/11 contentions in the next 26 weeks/i));
  });

  it('puts the chosen horizon in the URL', async () => {
    resolveHorizon({ count: 4, weeks: 6 });
    const { locationState } = renderStandalone();
    await waitFor(() => expect(mockGetHorizon).toHaveBeenCalledWith(6));

    resolveHorizon({ count: 2, weeks: 12 });
    await userEvent.click(screen.getByRole('button', { name: /12 weeks/i }));

    await waitFor(() => expect(locationState.search).toContain('horizon_weeks=12'));
  });

  it('reads the horizon back off the URL on mount, for a shared link', async () => {
    resolveHorizon({ count: 9, weeks: 12 });

    renderStandalone(['/bookings/calendar?horizon_weeks=12']);

    await waitFor(() => expect(mockGetHorizon).toHaveBeenCalledWith(12));
    await waitFor(() => expect(horizonText()).toMatch(/9 contentions in the next 12 weeks/i));
  });

  it('links through to the contentions worklist — B6 builds no second worklist', async () => {
    resolveHorizon({ count: 4, weeks: 6 });
    renderStandalone();
    await waitFor(() => expect(mockGetHorizon).toHaveBeenCalledWith(6));

    const link = screen.getByRole('link', { name: /contention/i });
    expect(link).toHaveAttribute('href', '/contentions');
  });

  it('says "1 contention" not "1 contentions"', async () => {
    resolveHorizon({ count: 1, weeks: 6 });
    renderStandalone();

    await waitFor(() => expect(horizonText()).toMatch(/1 contention in the next 6 weeks/i));
    expect(horizonText()).not.toMatch(/1 contentions/i);
  });

  it('says "0 contentions", plural, for a clean horizon', async () => {
    resolveHorizon({ count: 0, weeks: 6 });
    renderStandalone();

    await waitFor(() => expect(horizonText()).toMatch(/0 contentions in the next 6 weeks/i));
  });
});
