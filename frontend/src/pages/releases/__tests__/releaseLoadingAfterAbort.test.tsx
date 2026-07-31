import { render, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import ReleaseList from '../ReleaseList';
import ReleaseTimeline from '../ReleaseTimeline';

// No HTTP — this is about the interaction between useServerGrid's
// abort-on-unmount cleanup and the release slice's loading flag, not about
// what any endpoint actually returns.
vi.mock('../../../services/releaseService', () => ({
  releaseService: {
    list: vi.fn(),
    listBacklogChanges: vi.fn().mockResolvedValue([]),
    listTimeline: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock('../../../services/systemService', () => ({
  systemService: { listSystems: vi.fn().mockResolvedValue([]) },
}));

import { releaseService } from '../../../services/releaseService';

// Regression for the bug: useServerGrid's unmount cleanup
// (`useEffect(() => () => inFlight.current?.abort(), [])`) aborts an
// in-flight fetchReleases request when ReleaseList unmounts. That dispatches
// `fetchReleases.rejected` with `meta.aborted: true`, and the slice's
// supersession guard (`if (action.meta.aborted) return;`) — correct for a
// request superseded by a newer one — deliberately leaves `loading`
// untouched here too, because on unmount there is no successor pending
// action to have raised it back up. So `state.release.loading` stays stuck
// at `true` for the rest of the SPA session.
//
// That alone isn't directly observable (nothing renders while ReleaseList is
// unmounted), but it surfaces the moment the user opens Calendar or Timeline
// next: before this fix, neither thunk touched `state.release.loading` at
// all, so the stuck `true` from the aborted list fetch just sat there
// forever — permanent spinner, and Timeline's "No releases with phases
// found." empty state (gated on `!loading`) could never render.
describe('release loading regression — abort on unmount must not hang a later page', () => {
  it('does not leave state.release.loading stuck true after leaving /releases mid-fetch and opening Timeline', async () => {
    // Never resolves — the request will still be in flight when we unmount.
    vi.mocked(releaseService.list).mockReturnValue(new Promise(() => {}));

    const { unmount } = render(
      <Provider store={store}>
        <MemoryRouter initialEntries={['/releases']}>
          <ReleaseList />
        </MemoryRouter>
      </Provider>
    );
    await waitFor(() => expect(store.getState().release.loading).toBe(true));

    // Simulates navigating away from /releases while the fetch is in flight
    // — useServerGrid's unmount cleanup aborts it.
    unmount();

    // Simulates then clicking Timeline.
    const { getByText } = render(
      <Provider store={store}>
        <MemoryRouter initialEntries={['/releases/timeline']}>
          <ReleaseTimeline />
        </MemoryRouter>
      </Provider>
    );

    await waitFor(() => expect(store.getState().release.loading).toBe(false));
    await waitFor(() =>
      expect(getByText('No releases with phases found.')).toBeInTheDocument()
    );
  });
});
