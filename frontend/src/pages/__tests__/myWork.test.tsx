import { configureStore } from '@reduxjs/toolkit';
import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import * as myWorkServiceModule from '../../services/myWorkService';
import MyWork from '../MyWork';
import myWorkReducer, { fetchMyWork } from '../../store/myWorkSlice';
import type { MyWorkResponse, QueueResult, WorkItem } from '../../types/myWork';

// No `renderWithStore` helper exists in this codebase (checked before
// writing this test) — inlined the same way
// EnvironmentProjectsPanel.test.tsx / EnvironmentGroupsPanel.test.tsx do.
vi.mock('../../services/myWorkService', () => ({
  myWorkService: {
    getMyWork: vi.fn(),
  },
}));

const { myWorkService } = myWorkServiceModule as unknown as {
  myWorkService: { getMyWork: ReturnType<typeof vi.fn> };
};

/**
 * A NON-EMPTY baseline for every queue (one row each), so a test that
 * overrides a single queue to be empty or failed sees exactly one
 * "Nothing waiting on you" / "Couldn't load" — not five, which is what an
 * all-empty baseline would produce and `getByText` would then correctly
 * refuse as ambiguous.
 */
function queueWithOneRow(key: string): QueueResult {
  return {
    count: 1,
    items: [{ id: 1, title: `${key} item`, subtitle: null, url: `/${key}`, due: null }],
    failed: false,
  };
}

const allFive: MyWorkResponse['queues'] = {
  environment_requests: queueWithOneRow('environment_requests'),
  contentions: queueWithOneRow('contentions'),
  decommissions: queueWithOneRow('decommissions'),
  pir_actions: queueWithOneRow('pir_actions'),
  incidents: queueWithOneRow('incidents'),
};

const okQueue: QueueResult = { count: 0, items: [], failed: false };

// All-empty baseline, used only by the "at most five rows" test below: with
// `allFive`'s one-row-per-queue baseline instead, the OTHER four cards would
// contribute four more `queue-row`s and the assertion of exactly five would
// pass for the wrong reason (or fail outright).
const emptyFour: MyWorkResponse['queues'] = {
  environment_requests: okQueue,
  contentions: okQueue,
  decommissions: okQueue,
  pir_actions: okQueue,
  incidents: okQueue,
};

const fiveItems: WorkItem[] = Array.from({ length: 5 }, (_, i) => ({
  id: i + 1,
  title: `Incident ${i + 1}`,
  subtitle: 'critical · open',
  url: `/incidents/${i + 1}`,
  due: null,
}));

/**
 * Preloads the store with a `fetchMyWork.fulfilled` dispatch (so the page
 * has data on first render) AND mocks the service the component's own
 * mount-effect will call again — with the SAME response, so the second,
 * real dispatch this component fires on mount is idempotent rather than a
 * source of flakiness.
 */
function renderWithStore(ui: React.ReactElement, queues: MyWorkResponse['queues']) {
  const response: MyWorkResponse = { as_of: '2026-09-04T00:00:00Z', queues };
  myWorkService.getMyWork.mockResolvedValue(response);

  const store = configureStore({ reducer: { myWork: myWorkReducer } });
  store.dispatch({ type: fetchMyWork.fulfilled.type, payload: response });

  return render(
    <Provider store={store}>
      <MemoryRouter>{ui}</MemoryRouter>
    </Provider>
  );
}

describe('MyWork', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders a card for every queue, including empty ones', async () => {
    // §5: "cards are never hidden" — a hidden card is indistinguishable from
    // a queue you are not a member of.
    renderWithStore(<MyWork />, { ...allFive, contentions: { count: 0, items: [], failed: false } });
    expect(await screen.findByRole('heading', { name: /contentions/i })).toBeInTheDocument();
    expect(screen.getByText('Nothing waiting on you')).toBeInTheDocument();
  });

  it('a FAILED queue is not rendered as an empty one', async () => {
    // The distinction this whole degradation design exists for.
    renderWithStore(<MyWork />, {
      ...allFive,
      incidents: { count: 0, items: [], failed: true },
    });
    expect(await screen.findByText(/couldn't load/i)).toBeInTheDocument();
    expect(screen.queryByText('Nothing waiting on you')).not.toBeInTheDocument();
  });

  it('View all links to the worklist with the same filter in the URL', async () => {
    renderWithStore(<MyWork />, allFive);
    const link = await screen.findByRole('link', { name: /view all incidents/i });
    expect(link).toHaveAttribute('href', '/incidents?open=true');
  });

  it('shows at most five rows even when the count is higher', async () => {
    renderWithStore(<MyWork />, {
      ...emptyFour,
      incidents: { count: 12, items: fiveItems, failed: false },
    });
    expect(await screen.findAllByTestId('queue-row')).toHaveLength(5);
    expect(screen.getByText('12')).toBeInTheDocument();
  });

  it('a whole-response failure does not render any card as empty', async () => {
    // One level up from the per-queue distinction above: `/me/work` itself
    // fails (network error, or a 5xx before any per-queue try/except on the
    // backend even ran) — `data` never arrives at all. `data?.queues[key]
    // ?? EMPTY_QUEUE` would hand every one of the five cards an empty,
    // non-failed queue here, and all five would confidently say "Nothing
    // waiting on you" about a response that never came back. No store
    // preload this time — `data` starts genuinely null, the way it does on
    // a real first-load failure.
    myWorkService.getMyWork.mockRejectedValue(new Error('network down'));
    const store = configureStore({ reducer: { myWork: myWorkReducer } });

    render(
      <Provider store={store}>
        <MemoryRouter>
          <MyWork />
        </MemoryRouter>
      </Provider>
    );

    expect(await screen.findAllByText(/couldn't load/i)).toHaveLength(5);
    expect(screen.queryByText('Nothing waiting on you')).not.toBeInTheDocument();
  });

  it('a malformed 200 (queues missing) renders without crashing (finding 4)', async () => {
    // `data?.queues[cfg.key]` used to throw the moment `data` arrived but
    // `queues` did not match the schema — dropping the WHOLE page (and, via
    // the same selector, every other route's nav badge) to the root
    // ErrorBoundary rather than showing five degraded cards.
    myWorkService.getMyWork.mockResolvedValue(
      { as_of: '2026-09-04T00:00:00Z' } as unknown as MyWorkResponse
    );
    const store = configureStore({ reducer: { myWork: myWorkReducer } });

    render(
      <Provider store={store}>
        <MemoryRouter>
          <MyWork />
        </MemoryRouter>
      </Provider>
    );

    expect(await screen.findByRole('heading', { name: /my work/i })).toBeInTheDocument();
    // No crash either way this renders — asserting the ordinary "empty"
    // fallback rather than "failed" is a statement about today's choice
    // (no `error` was set; this was a 200), not a claim that failed is wrong.
    expect(await screen.findAllByText('Nothing waiting on you')).toHaveLength(5);
  });
});
