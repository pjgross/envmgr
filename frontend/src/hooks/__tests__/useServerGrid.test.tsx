import { act, render, renderHook } from '@testing-library/react';
import {
  MemoryRouter,
  UNSAFE_createMemoryHistory,
  unstable_HistoryRouter as HistoryRouter,
  useLocation,
  useNavigate,
  type NavigateFunction,
} from 'react-router-dom';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useServerGrid } from '../useServerGrid';

function wrapper(initialEntries: string[]) {
  return ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
  );
}

/**
 * A wrapper that, alongside rendering the hook's children, exposes the live
 * `navigate` function and current `location.search` to the test — so a test
 * can drive a navigation the hook itself did not cause (Back, a `<Link>`)
 * and observe what the hook does to the URL afterwards.
 */
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

function setup(url = '/releases') {
  const onFetch = vi.fn();
  const hook = renderHook(
    () => useServerGrid({ endpoint: 'releases', filterKeys: ['status'], onFetch }),
    { wrapper: wrapper([url]) }
  );
  return { ...hook, onFetch };
}

describe('useServerGrid', () => {
  it('fetches the endpoint default sort on mount', () => {
    const { onFetch } = setup();
    expect(onFetch).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 25, offset: 0, sort_by: 'created_at', sort_dir: 'desc' })
    );
  });

  it('restores page, sort and filters from the URL', () => {
    const { result } = setup('/releases?page=2&page_size=50&sort_by=name&sort_dir=asc&status=draft');
    expect(result.current.paginationModel).toEqual({ page: 2, pageSize: 50 });
    expect(result.current.sortModel).toEqual([{ field: 'name', sort: 'asc' }]);
    expect(result.current.filters.status).toBe('draft');
  });

  it('never sends a sort_by outside the whitelist, even from a URL', () => {
    const { onFetch } = setup('/releases?sort_by=phase_count');
    expect(onFetch).toHaveBeenCalledWith(
      expect.objectContaining({ sort_by: 'created_at' })
    );
    expect(onFetch).not.toHaveBeenCalledWith(
      expect.objectContaining({ sort_by: 'phase_count' })
    );
  });

  it('resets to page 0 when a filter changes', () => {
    const { result, onFetch } = setup('/releases?page=3');
    onFetch.mockClear();
    act(() => result.current.setFilter('status', 'draft'));
    expect(result.current.paginationModel.page).toBe(0);
    expect(onFetch).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 }));
  });

  it('resets to page 0 when the sort changes', () => {
    const { result, onFetch } = setup('/releases?page=3');
    onFetch.mockClear();
    act(() => result.current.onSortModelChange([{ field: 'name', sort: 'asc' }]));
    expect(result.current.paginationModel.page).toBe(0);
    expect(onFetch).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0, sort_by: 'name', sort_dir: 'asc' })
    );
  });

  it('falls back to the default sort when the grid clears the sort model', () => {
    const { result, onFetch } = setup('/releases?sort_by=name&sort_dir=asc');
    onFetch.mockClear();
    act(() => result.current.onSortModelChange([]));
    expect(result.current.sortModel).toEqual([{ field: 'created_at', sort: 'desc' }]);
    expect(onFetch).toHaveBeenLastCalledWith(
      expect.objectContaining({ sort_by: 'created_at', sort_dir: 'desc' })
    );
  });

  it('fetches the next page when the pagination model changes', () => {
    const { result, onFetch } = setup();
    onFetch.mockClear();
    act(() => result.current.onPaginationModelChange({ page: 2, pageSize: 50 }));
    expect(result.current.paginationModel).toEqual({ page: 2, pageSize: 50 });
    expect(onFetch).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 50, offset: 100 }));
  });

  it('refetches when a filter changes on page 0, where no page reset can mask it', () => {
    const { result, onFetch } = setup(); // no ?page= — offset stays 0
    onFetch.mockClear();
    act(() => result.current.setFilter('status', 'draft'));
    expect(onFetch).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0, status: 'draft' })
    );
  });

  it('keeps filters referentially stable across a re-render that changes nothing', () => {
    const { result, rerender } = setup();
    const first = result.current.filters;
    rerender();
    expect(result.current.filters).toBe(first);
  });

  it('falls back to safe page/page_size defaults when the URL values are invalid', () => {
    const { result } = setup('/releases?page=abc&page_size=-5');
    expect(result.current.paginationModel).toEqual({ page: 0, pageSize: 25 });
  });

  // DataTable's pageSizeOptions is the fixed set [10, 25, 50, 100]. A
  // page_size that's a valid integer 1-100 but not one of those options
  // (e.g. a hand-edited link) still built a valid request, but produced a
  // MUI out-of-range console warning and a blank page-size select.
  it('clamps an in-range but non-option page_size to the default', () => {
    const { result, onFetch } = setup('/releases?page_size=7');
    expect(result.current.paginationModel).toEqual({ page: 0, pageSize: 25 });
    expect(onFetch).toHaveBeenCalledWith(expect.objectContaining({ limit: 25 }));
  });

  it('accepts every page_size DataTable actually offers', () => {
    [10, 25, 50, 100].forEach((pageSize) => {
      const { result } = setup(`/releases?page_size=${pageSize}`);
      expect(result.current.paginationModel.pageSize).toBe(pageSize);
    });
  });

  it('keeps setFilter referentially stable across a re-render that changes nothing', () => {
    // debounceKeys, like filterKeys, is typically an inline array literal at
    // the call site — a fresh reference every render. setFilter must key its
    // memoisation off the array's contents, not its identity, or every
    // caller re-render would hand the grid a new setFilter and defeat any
    // memoisation downstream (e.g. a memoised filter input).
    const onFetch = vi.fn();
    const { result, rerender } = renderHook(
      () =>
        useServerGrid({
          endpoint: 'releases',
          filterKeys: ['search'],
          debounceKeys: ['search'],
          onFetch,
        }),
      { wrapper: wrapper(['/releases']) }
    );
    const first = result.current.setFilter;
    rerender();
    expect(result.current.setFilter).toBe(first);
  });
});

describe('useServerGrid resilience', () => {
  it("resyncs the URL ref on render, so a navigation the hook didn't cause isn't clobbered by a stale snapshot", () => {
    // A user presses Back (or follows a <Link>) that changes the query
    // string without going through this hook's own `patch`. The next thing
    // `patch` writes must be layered on top of that navigation, not on top
    // of whatever URL existed the last time `patch` itself ran.
    const { Wrapper, state } = locationHarness(['/releases']);
    const onFetch = vi.fn();
    const { result } = renderHook(
      () => useServerGrid({ endpoint: 'releases', filterKeys: ['status'], onFetch }),
      { wrapper: Wrapper }
    );

    act(() => result.current.setFilter('status', 'draft'));
    expect(state.search).toBe('?status=draft');

    // Navigation the hook did not cause — e.g. Back, or a <Link>.
    act(() => state.navigate?.('/releases?page=3'));
    expect(state.search).toBe('?page=3');

    act(() => result.current.onPaginationModelChange({ page: 4, pageSize: 25 }));

    // The abandoned `status=draft` must not resurface — the write is layered
    // on the navigated-to URL, not the pre-navigation snapshot.
    expect(state.search).toBe('?page=4&page_size=25');
  });

  describe('debounce timing', () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('debounces a text filter but not a select', async () => {
      const onFetch = vi.fn();
      const { result } = renderHook(
        () =>
          useServerGrid({
            endpoint: 'releases',
            filterKeys: ['search', 'status'],
            debounceKeys: ['search'],
            onFetch,
          }),
        { wrapper: wrapper(['/releases']) }
      );
      onFetch.mockClear();

      act(() => result.current.setFilter('search', 'pay'));
      expect(onFetch).not.toHaveBeenCalled();
      act(() => vi.advanceTimersByTime(300));
      expect(onFetch).toHaveBeenCalledTimes(1);

      onFetch.mockClear();
      act(() => result.current.setFilter('status', 'draft'));
      expect(onFetch).toHaveBeenCalledTimes(1);
    });

    it('does not lose an immediate filter set while a debounced filter is pending', () => {
      // Regression: `patch` used to be rebuilt (new identity) whenever the URL
      // changed, so the debounce timer's callback closed over a stale `patch`
      // whose snapshot predated the immediate `status` write. When the timer
      // fired, it rebuilt the query string from that stale snapshot and
      // silently reverted `status`.
      const onFetch = vi.fn();
      const { result } = renderHook(
        () =>
          useServerGrid({
            endpoint: 'releases',
            filterKeys: ['search', 'status'],
            debounceKeys: ['search'],
            onFetch,
          }),
        { wrapper: wrapper(['/releases']) }
      );
      onFetch.mockClear();

      act(() => result.current.setFilter('search', 'pay'));
      act(() => result.current.setFilter('status', 'draft'));
      act(() => vi.advanceTimersByTime(300));

      expect(result.current.filters).toEqual({ search: 'pay', status: 'draft' });
      expect(onFetch).toHaveBeenLastCalledWith(
        expect.objectContaining({ search: 'pay', status: 'draft' })
      );
    });

    it('does not let one debounced key cancel another pending debounced key', () => {
      // Regression: a single shared timer meant the second `setFilter` call's
      // `clearTimeout` cancelled the first key's pending write outright, so it
      // never fired at all — not even the stale-closure result, just silently
      // dropped.
      const onFetch = vi.fn();
      const { result } = renderHook(
        () =>
          useServerGrid({
            endpoint: 'releases',
            filterKeys: ['search', 'notes'],
            debounceKeys: ['search', 'notes'],
            onFetch,
          }),
        { wrapper: wrapper(['/releases']) }
      );
      onFetch.mockClear();

      act(() => result.current.setFilter('search', 'pay'));
      act(() => result.current.setFilter('notes', 'urgent'));
      act(() => vi.advanceTimersByTime(300));

      expect(result.current.filters).toEqual({ search: 'pay', notes: 'urgent' });
      expect(onFetch).toHaveBeenLastCalledWith(
        expect.objectContaining({ search: 'pay', notes: 'urgent' })
      );
    });

    it('coalesces rapid keystrokes into a single request carrying the final value', () => {
      // Without clearTimeout-ing the previous pending write, every keystroke
      // would schedule its own independent 300ms timer and each would fire —
      // exactly what the debounce exists to prevent.
      const onFetch = vi.fn();
      const { result } = renderHook(
        () =>
          useServerGrid({
            endpoint: 'releases',
            filterKeys: ['search'],
            debounceKeys: ['search'],
            onFetch,
          }),
        { wrapper: wrapper(['/releases']) }
      );
      onFetch.mockClear();

      // Advance in separate 100ms steps (rather than one final 300ms jump) so
      // an uncleared earlier timer would fire in its own commit — bunching
      // the advance into a single call lets React's automatic batching
      // collapse multiple same-tick timer firings into one commit even
      // without the clearTimeout, which would make this test pass either way.
      act(() => result.current.setFilter('search', 'p'));
      act(() => vi.advanceTimersByTime(100));
      act(() => result.current.setFilter('search', 'pa'));
      act(() => vi.advanceTimersByTime(100));
      act(() => result.current.setFilter('search', 'pay'));
      act(() => vi.advanceTimersByTime(100)); // t=300: the stale first timer, if not cleared
      act(() => vi.advanceTimersByTime(100)); // t=400: the stale second timer, if not cleared
      act(() => vi.advanceTimersByTime(100)); // t=500: the real, final timer

      expect(onFetch).toHaveBeenCalledTimes(1);
      expect(onFetch).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'pay' }));
    });

    it('does not let a debounced timer outlive unmount and rewrite a later URL', () => {
      // react-router's `navigate` keeps working after the component that
      // called `useNavigate` unmounts, so a debounce timer that survives
      // unmount will still fire and rewrite the query string of whatever
      // page the user has since moved to.
      const state: { search: string; setFilter?: (key: string, value: string) => void } = {
        search: '',
      };

      function Watcher() {
        state.search = useLocation().search;
        return null;
      }

      function Child() {
        const grid = useServerGrid({
          endpoint: 'releases',
          filterKeys: ['search'],
          debounceKeys: ['search'],
          onFetch: vi.fn(),
        });
        state.setFilter = grid.setFilter;
        return null;
      }

      function Harness({ mounted }: { mounted: boolean }) {
        return (
          <MemoryRouter initialEntries={['/releases']}>
            <Watcher />
            {mounted && <Child />}
          </MemoryRouter>
        );
      }

      const { rerender } = render(<Harness mounted />);

      act(() => state.setFilter?.('search', 'pay'));
      expect(state.search).toBe('');

      rerender(<Harness mounted={false} />);
      act(() => vi.advanceTimersByTime(300));

      expect(state.search).toBe('');
    });
  });

  it('aborts the previous request when the parameters change', () => {
    // The hook does not apply responses — the thunk's fulfilled reducer writes
    // the slice. Noticing a superseded response therefore cannot stop it
    // painting; only aborting it can, because an aborted RTK thunk never
    // reaches fulfilled.
    const aborts: number[] = [];
    let call = 0;
    const onFetch = vi.fn(() => {
      const id = call++;
      return { abort: () => aborts.push(id) };
    });
    const { result } = renderHook(
      () => useServerGrid({ endpoint: 'releases', filterKeys: [], onFetch }),
      { wrapper: wrapper(['/releases']) }
    );

    act(() => result.current.onPaginationModelChange({ page: 1, pageSize: 25 }));
    act(() => result.current.onPaginationModelChange({ page: 2, pageSize: 25 }));

    // The mount request and the page-1 request are both superseded; the
    // in-flight page-2 request is not aborted.
    expect(aborts).toEqual([0, 1]);
  });

  it('aborts the in-flight request on unmount', () => {
    let aborted = false;
    const onFetch = vi.fn(() => ({ abort: () => { aborted = true; } }));
    const { unmount } = renderHook(
      () => useServerGrid({ endpoint: 'releases', filterKeys: [], onFetch }),
      { wrapper: wrapper(['/releases']) }
    );

    unmount();

    expect(aborted).toBe(true);
  });

  it('navigates with replace so a grid interaction does not grow browser history', () => {
    // Every filter/sort/page change writes a new URL. If that write were a
    // push instead of a replace, each interaction would add its own history
    // entry, and Back would walk through every intermediate grid state
    // instead of leaving the page — history.index tracks the stack position
    // the way an actual push/replace does, so it directly observes that.
    const history = UNSAFE_createMemoryHistory({ initialEntries: ['/releases'] });
    const onFetch = vi.fn();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <HistoryRouter history={history}>{children}</HistoryRouter>
    );
    const { result } = renderHook(
      () => useServerGrid({ endpoint: 'releases', filterKeys: ['status'], onFetch }),
      { wrapper }
    );
    const startIndex = history.index;

    act(() => result.current.setFilter('status', 'draft'));
    act(() => result.current.onPaginationModelChange({ page: 1, pageSize: 25 }));
    act(() => result.current.onSortModelChange([{ field: 'name', sort: 'asc' }]));

    expect(history.index).toBe(startIndex);
  });

  describe('refetch', () => {
    it('re-issues the current query with identical params', async () => {
      // A create or delete must be able to re-ask the server, because the
      // correct next page cannot be computed in the browser: a new row need
      // not belong on the current page at all.
      const onFetch = vi.fn();
      const hook = renderHook(
        () => useServerGrid({ endpoint: 'releases', filterKeys: ['status'], onFetch }),
        { wrapper: wrapper(['/releases']) }
      );

      expect(onFetch).toHaveBeenCalledTimes(1);
      const first = onFetch.mock.calls[0][0];

      await act(async () => {
        hook.result.current.refetch();
      });

      expect(onFetch).toHaveBeenCalledTimes(2);
      expect(onFetch.mock.calls[1][0]).toEqual(first);
    });

    it('keeps a stable identity so it can sit in an effect dependency list', () => {
      const onFetch = vi.fn();
      const hook = renderHook(
        () => useServerGrid({ endpoint: 'releases', filterKeys: ['status'], onFetch }),
        { wrapper: wrapper(['/releases']) }
      );
      const before = hook.result.current.refetch;
      hook.rerender();
      expect(hook.result.current.refetch).toBe(before);
    });
  });

  it('clamps to the last valid page when the offset runs past the total', () => {
    const onFetch = vi.fn();
    const { result, rerender } = renderHook(
      ({ total }) =>
        useServerGrid({ endpoint: 'releases', filterKeys: [], onFetch, total }),
      { wrapper: wrapper(['/releases?page=4&page_size=25']), initialProps: { total: 200 } }
    );
    onFetch.mockClear();

    // A row deleted elsewhere shrinks the set under the current offset.
    rerender({ total: 30 });

    expect(result.current.paginationModel.page).toBe(1);
    expect(onFetch).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 25 }));
  });
});
