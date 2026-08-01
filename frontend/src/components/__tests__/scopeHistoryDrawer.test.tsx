import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { describe, expect, it, vi } from 'vitest';
import ScopeHistoryDrawer from '../releases/ScopeHistoryDrawer';

const list = vi.fn();
vi.mock('../../services/releaseService', () => ({
  releaseService: { list: (...args: unknown[]) => list(...args) },
}));

/**
 * `sliceReleases` is what ReleaseList happens to have left in the store —
 * deliberately empty here, standing in for a grid page that holds none of the
 * releases this history refers to.
 */
function renderDrawerWithHistory(opts: {
  sliceReleases: { id: number; name: string }[];
  history: {
    from_release_id: number | null;
    to_release_id: number | null;
    moved_at: string;
    notes: string | null;
  }[];
}) {
  const store = configureStore({
    reducer: {
      release: () => ({
        list: opts.sliceReleases,
        total: 0,
        loading: false,
        listLoading: false,
        error: null,
        detail: null,
        changeReleaseHistory: opts.history,
        changeStatusHistory: [],
      }),
    },
  });
  return render(
    <Provider store={store}>
      <ScopeHistoryDrawer open onClose={() => {}} changeId={1} itemTitle="Item" />
    </Provider>
  );
}

describe('ScopeHistoryDrawer', () => {
  it('names a release that is not on the grid current page', async () => {
    // The release slice holds ReleaseList's current 25-row page. A scope item
    // moved between older releases must still render their names, never #47.
    list.mockResolvedValue({ rows: [{ id: 47, name: 'Mortgage R2' }], total: 1 });

    renderDrawerWithHistory({
      sliceReleases: [],
      history: [
        { from_release_id: null, to_release_id: 47, moved_at: '2026-07-01T00:00:00Z', notes: null },
      ],
    });

    await waitFor(() => expect(screen.getByText(/Mortgage R2/)).toBeInTheDocument());
    expect(screen.queryByText(/Release #47/)).not.toBeInTheDocument();
  });
});
