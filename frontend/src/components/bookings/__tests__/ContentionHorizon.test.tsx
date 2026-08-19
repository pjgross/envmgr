import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { configureStore } from '@reduxjs/toolkit';
import { Provider } from 'react-redux';
import { MemoryRouter, useLocation, type NavigateFunction, useNavigate } from 'react-router-dom';
import type { ReactNode } from 'react';
import { AxiosError } from 'axios';
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

  // THE STRANDING BUG, at the level a user actually experiences it: rapid
  // horizon switching where the OLDER request's response lands after the
  // NEWER one's. Without contentionForecastSlice's currentRequestId guard,
  // the stale response would overwrite `state.weeks` back to the outgoing
  // selection, and — because ContentionHorizon only re-dispatches on a
  // change to `weeks` (the URL's, which hasn't moved again) — nothing would
  // ever re-fetch to correct it. The component would sit in its skeleton
  // (fetchedWeeks !== weeks) indefinitely, with no error shown.
  it('an out-of-order response does not strand the summary in its skeleton', async () => {
    resolveHorizon({ count: 4, weeks: 6 });
    renderStandalone();
    await waitFor(() => expect(mockGetHorizon).toHaveBeenCalledWith(6));
    await waitFor(() => expect(horizonText()).toMatch(/4 contentions in the next 6 weeks/i));

    let resolveOlder!: (value: ContentionHorizonPayload) => void;
    let resolveNewer!: (value: ContentionHorizonPayload) => void;
    const olderPromise = new Promise<ContentionHorizonPayload>((resolve) => {
      resolveOlder = resolve;
    });
    const newerPromise = new Promise<ContentionHorizonPayload>((resolve) => {
      resolveNewer = resolve;
    });

    // Two rapid clicks: 2 weeks, then 26 weeks — the older (2-week) request
    // is still in flight when the newer (26-week) one starts.
    mockGetHorizon.mockReturnValueOnce(olderPromise);
    await userEvent.click(screen.getByRole('button', { name: /^2 weeks$/i }));
    await waitFor(() => expect(mockGetHorizon).toHaveBeenCalledWith(2));

    mockGetHorizon.mockReturnValueOnce(newerPromise);
    await userEvent.click(screen.getByRole('button', { name: /26 weeks/i }));
    await waitFor(() => expect(mockGetHorizon).toHaveBeenCalledWith(26));

    // Resolve OUT OF ORDER: newer settles first, older arrives late.
    resolveNewer({ count: 11, weeks: 26 });
    await waitFor(() => expect(horizonText()).toMatch(/11 contentions in the next 26 weeks/i));

    resolveOlder({ count: 1, weeks: 2 });
    // The stale response must not be applied on top of the settled, current
    // one — held across a tick so a wrongly-applied update has a chance to
    // show up before the assertion runs.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(horizonText()).toMatch(/11 contentions in the next 26 weeks/i);
    expect(horizonText()).not.toMatch(/1 contention in the next 2 weeks/i);
  });

  // FINDING 2 — the allow-list is the only thing standing between a
  // hand-edited/stale URL and a request the backend 422s (it bounds `weeks`
  // at 1-104). An out-of-range or non-numeric value must fall back to the
  // default rather than ever reaching the network unvalidated.
  it('falls back to the default horizon for an out-of-range ?horizon_weeks=', async () => {
    resolveHorizon({ count: 4, weeks: 6 });
    renderStandalone(['/bookings/calendar?horizon_weeks=99']);

    await waitFor(() => expect(mockGetHorizon).toHaveBeenCalledWith(6));
    expect(mockGetHorizon).not.toHaveBeenCalledWith(99);
  });

  it('falls back to the default horizon for a non-numeric ?horizon_weeks=', async () => {
    resolveHorizon({ count: 4, weeks: 6 });
    renderStandalone(['/bookings/calendar?horizon_weeks=abc']);

    await waitFor(() => expect(mockGetHorizon).toHaveBeenCalledWith(6));
    expect(mockGetHorizon).not.toHaveBeenCalledWith(NaN);
  });

  // FINDING 3 — a plain Error carrying the final text would pass here while
  // the app is broken (RTK's default miniSerializeError drops
  // response.data.detail); a real AxiosError shape is what
  // rejectWithValue(formatApiError(...)) actually has to unwrap.
  it('renders the server reason when the horizon fetch fails', async () => {
    const err = new AxiosError('Request failed with status code 500');
    err.response = {
      data: { detail: 'Failed to compute the contention forecast' },
      status: 500,
      statusText: 'Internal Server Error',
      headers: {},
      config: {} as never,
    } as never;
    mockGetHorizon.mockRejectedValueOnce(err);

    renderStandalone();

    await waitFor(() =>
      expect(horizonText()).toMatch(/failed to compute the contention forecast/i)
    );
    // Guards against a fix that shows the generic axios message alongside or
    // instead of the server's reason.
    expect(horizonText()).not.toMatch(/status code 500/i);
  });
});
