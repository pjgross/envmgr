/**
 * Task 7: the *My work* nav item's count badge.
 *
 * Rules under test (see the task brief):
 *  1. The badge is the SUM of the five queues' `count`, not the queue count
 *     or the capped `items.length`.
 *  2. Fetched on mount and on every route change — NOTHING ELSE. No
 *     `setInterval`/polling; advancing fake timers must add no fetch.
 *  3. No badge at all when every queue is empty (a "0" is noise).
 *
 * Renders the real `AppLayout` (not just `NavDrawer` in isolation) because
 * rule 2 is about wiring — AppLayout is where `useMyWork` gets called and
 * where route changes are observed — so only an integration render can prove
 * a route change actually triggers a refetch.
 */
import { configureStore } from '@reduxjs/toolkit';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import AppLayout from '../AppLayout';
import authReducer from '../../store/authSlice';
import uiReducer from '../../store/uiSlice';
import myWorkReducer from '../../store/myWorkSlice';
import * as myWorkServiceModule from '../../services/myWorkService';
import type { MyWorkQueueKey, MyWorkResponse, QueueResult } from '../../types/myWork';

vi.mock('../../services/authService', () => ({ authService: { logout: vi.fn() } }));
vi.mock('../../services/myWorkService', () => ({
  myWorkService: { getMyWork: vi.fn() },
}));

const { myWorkService } = myWorkServiceModule as unknown as {
  myWorkService: { getMyWork: ReturnType<typeof vi.fn> };
};

const QUEUE_KEYS: MyWorkQueueKey[] = [
  'environment_requests',
  'contentions',
  'decommissions',
  'pir_actions',
  'incidents',
];

function q(count: number, failed = false): QueueResult {
  return { count, items: [], failed };
}

/** Builds a `MyWorkResponse` from five counts, keyed positionally onto `QUEUE_KEYS`. */
function workResponse(counts: number[], failed: boolean[] = [false, false, false, false, false]): MyWorkResponse {
  const queues = {} as MyWorkResponse['queues'];
  QUEUE_KEYS.forEach((key, i) => {
    queues[key] = q(counts[i], failed[i]);
  });
  return { as_of: '2026-09-04T00:00:00Z', queues };
}

function Probe() {
  const navigate = useNavigate();
  return (
    <div>
      <button onClick={() => navigate('/releases')}>go elsewhere</button>
    </div>
  );
}

function renderApp(initialPath = '/dashboard') {
  const store = configureStore({
    reducer: { auth: authReducer, ui: uiReducer, myWork: myWorkReducer },
    preloadedState: {
      auth: {
        user: { id: 1, username: 'admin', email: 'a@x', role: 'Developer', tenant_id: 1, is_master_admin: false },
        token: 't',
        isAuthenticated: true,
        authInitialized: true,
        impersonationMode: false,
        impersonatingTenant: null,
        originalToken: null,
      },
    },
  });
  render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="*" element={<Probe />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </Provider>
  );
}

describe('the My work nav badge', () => {
  beforeEach(() => {
    localStorage.clear();
    // jsdom has no matchMedia — AppLayout's useMediaQuery(up('md')) needs one
    // so the drawer renders permanent (desktop) rather than a closed,
    // aria-hidden temporary drawer that hides every item inside it. Same
    // setup as AppLayout.test.tsx.
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it('shows the sum of the five counts', async () => {
    myWorkService.getMyWork.mockResolvedValue(workResponse([2, 0, 1, 3, 4]));
    renderApp();
    expect(await screen.findByText('10')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'My work, 10 items waiting' })).toBeInTheDocument();
  });

  it('renders no badge when every queue is empty', async () => {
    myWorkService.getMyWork.mockResolvedValue(workResponse([0, 0, 0, 0, 0]));
    renderApp();
    // Wait for the fetch to resolve (the button carries its plain label with
    // no fetch pending) before asserting the negative.
    expect(await screen.findByRole('button', { name: 'My work' })).toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('refetches on route change, and does not poll', async () => {
    // Fake timers are installed BEFORE render, not after: a `setInterval`
    // registered while real timers are active keeps running on the real
    // clock even once `vi.useFakeTimers()` is later called — advancing the
    // fake clock afterwards would never observe it, and the test would pass
    // for the wrong reason. Confirmed by mutation — see the report.
    vi.useFakeTimers();
    myWorkService.getMyWork.mockResolvedValue(workResponse([1, 0, 0, 0, 0]));
    renderApp();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(myWorkService.getMyWork).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByText('go elsewhere'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(myWorkService.getMyWork).toHaveBeenCalledTimes(2);

    // §5/the brief: "fetched on mount and on every route change ... No
    // polling." Advancing the clock with no further navigation must add
    // nothing — this is the assertion that fails the moment a
    // setInterval/setTimeout-based refetch is added anywhere in the chain.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(myWorkService.getMyWork).toHaveBeenCalledTimes(2);
  });

  it('shows an attention indicator, not a hidden badge, when every queue is empty because it failed', async () => {
    // A failed queue's count is always 0 (the schema default), so the naive
    // sum reads as "nothing waiting" — indistinguishable from a genuinely
    // empty inbox unless something else marks the difference. Rule 3 says a
    // true zero renders nothing; this is not a true zero.
    myWorkService.getMyWork.mockResolvedValue(workResponse([0, 0, 0, 0, 0], [true, false, false, false, false]));
    renderApp();
    expect(
      await screen.findByRole('button', { name: 'My work, some queues could not be checked' })
    ).toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });
});
