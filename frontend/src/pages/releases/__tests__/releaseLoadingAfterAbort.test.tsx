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
  systemService: { listSystems: vi.fn().mockResolvedValue({ rows: [], total: 0 }) },
}));

import { releaseService } from '../../../services/releaseService';

// Regression for the bug: useServerGrid's unmount cleanup
// (`useEffect(() => () => inFlight.current?.abort(), [])`) aborts an
// in-flight fetchReleases request when ReleaseList unmounts. That dispatches
// `fetchReleases.rejected` with `meta.aborted: true`, and the slice's
// supersession guard (`if (action.meta.aborted) return;`) — correct for a
// request superseded by a newer one — deliberately leaves the list's loading
// flag untouched here too, because on unmount there is no successor pending
// action to have raised it back up. So the list's own flag stays stuck at
// `true` for the rest of the SPA session.
//
// Originally `fetchReleases` shared `state.release.loading` with ~20 other
// thunks, so that stuck flag was directly observable on Calendar/Timeline —
// it was patched by giving those two their own loading transitions. Since
// then, `fetchReleases` was given its own `listLoading` flag (see
// `releaseSlice.ts`, `describe('listLoading', ...)` in releaseSlice.test.ts):
// the stuck flag is now structurally confined to `listLoading`, which only
// ReleaseList reads, so `state.release.loading` — what Calendar/Timeline
// read — is never touched by the aborted list fetch at all.
describe('release loading regression — abort on unmount must not hang a later page', () => {
  it('keeps state.release.loading and Timeline unaffected by listLoading left stuck true from an aborted list fetch', async () => {
    // Never resolves — the request will still be in flight when we unmount.
    vi.mocked(releaseService.list).mockReturnValue(new Promise(() => {}));

    const { unmount } = render(
      <Provider store={store}>
        <MemoryRouter initialEntries={['/releases']}>
          <ReleaseList />
        </MemoryRouter>
      </Provider>
    );
    await waitFor(() => expect(store.getState().release.listLoading).toBe(true));
    // The general flag was never touched by the list fetch in the first place.
    expect(store.getState().release.loading).toBe(false);

    // Simulates navigating away from /releases while the fetch is in flight
    // — useServerGrid's unmount cleanup aborts it. listLoading is now stuck
    // true (the documented, contained trade-off), but nothing but
    // ReleaseList reads listLoading, so it can't hang anything else.
    unmount();
    expect(store.getState().release.listLoading).toBe(true);

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
