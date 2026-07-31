import { useCallback, useEffect, useMemo, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  buildParams,
  resolveSort,
  type EndpointKey,
  type ServerGridParams,
  type SortDir,
} from './serverGridParams';

const DEFAULT_PAGE_SIZE = 25;

/**
 * `page`/`page_size` come straight out of the URL and are just as untrusted
 * as `sort_by` — a hand-edited or stale link can hand us `abc`, a negative
 * number, or something absurdly large. Fall back to a safe default rather
 * than shipping `NaN`/negative values to the network or to MUI DataGrid.
 */
const clampInt = (raw: string | null, fallback: number, min: number, max: number): number => {
  const n = Number(raw);
  return raw !== null && Number.isInteger(n) && n >= min && n <= max ? n : fallback;
};

/** What `dispatch(someThunk())` returns in Redux Toolkit: a promise with `.abort()`. */
export interface Abortable {
  abort: () => void;
}

// filterKeys/debounceKeys are typically inline array literals at the call
// site (a new reference every render); a shared empty-array default avoids
// rebuilding memoised callbacks that depend on it every render.
const NO_DEBOUNCE: string[] = [];

export interface UseServerGridOptions {
  endpoint: EndpointKey;
  filterKeys: string[];
  /** Return the value of `dispatch(thunk(params))` so the hook can cancel it. */
  onFetch: (params: ServerGridParams) => Abortable | void;
  /** Filter keys whose changes should be debounced — free-text inputs. */
  debounceKeys?: string[];
  /** Latest known total, used to clamp an offset that has run past the end. */
  total?: number;
}

export interface ServerGrid {
  paginationModel: { page: number; pageSize: number };
  sortModel: { field: string; sort: SortDir }[];
  onPaginationModelChange: (model: { page: number; pageSize: number }) => void;
  onSortModelChange: (model: { field: string; sort?: SortDir | null }[]) => void;
  filters: Record<string, string>;
  setFilter: (key: string, value: string) => void;
}

/**
 * Drives a server-side DataGrid from the URL.
 *
 * The URL is the source of truth so a refresh, a back button or a shared link
 * all reproduce the same view. Anything read out of it is untrusted: `sort_by`
 * is validated against the whitelist before a request is built, because the
 * server answers an unknown field with a 422 rather than a silent fallback.
 */
export function useServerGrid({
  endpoint,
  filterKeys,
  onFetch,
  debounceKeys = NO_DEBOUNCE,
  total,
}: UseServerGridOptions): ServerGrid {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const page = clampInt(searchParams.get('page'), 0, 0, Number.MAX_SAFE_INTEGER);
  const pageSize = clampInt(searchParams.get('page_size'), DEFAULT_PAGE_SIZE, 1, 100);
  const rawSortBy = searchParams.get('sort_by');
  const rawSortDir = searchParams.get('sort_dir');
  // `buildParams` below re-resolves sort_by/sort_dir itself rather than taking
  // this value directly; that's fine because `resolveSort` is pure and
  // idempotent, so the two calls are always consistent with each other.
  const sort = resolveSort(endpoint, rawSortBy, rawSortDir);

  // filterKeys is typically an inline array literal at the call site (a new
  // reference every render), so it can't be a useMemo dependency itself
  // without defeating the memo. Key on its stable string form instead.
  const filterKeysKey = filterKeys.join(' ');
  const filters = useMemo(() => {
    const out: Record<string, string> = {};
    filterKeys.forEach((key) => {
      const value = searchParams.get(key);
      if (value !== null) out[key] = value;
    });
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, filterKeysKey]);

  const params = useMemo(
    () =>
      buildParams({
        endpoint,
        page,
        pageSize,
        sortBy: sort.sort_by,
        sortDir: sort.sort_dir,
        filters,
      }),
    [endpoint, page, pageSize, sort.sort_by, sort.sort_dir, filters]
  );

  // Key the fetch effect on the *resolved* request, not a hand-maintained
  // list of raw URL values — that list previously omitted `endpoint` (an
  // endpoint change fetched nothing) and treated e.g. a filter moving into
  // or out of the "all"/"" sentinel as a change even though `buildParams`
  // drops that value either way, issuing a duplicate byte-identical GET.
  const paramsKey = JSON.stringify(params);

  const inFlight = useRef<Abortable | void>();

  useEffect(() => {
    // Abort the previous request rather than merely ignoring its reply: the
    // response is applied by the thunk's fulfilled reducer, which this hook
    // never sees. An aborted RTK thunk dispatches rejected with meta.aborted,
    // so the slice is never written with rows the user has moved past.
    inFlight.current?.abort();
    inFlight.current = onFetch(params);
    // onFetch is a fresh dispatch closure on every render, and `params` is a
    // fresh object every render too; `paramsKey` is what decides whether a
    // refetch is warranted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramsKey]);

  useEffect(() => () => inFlight.current?.abort(), []);

  // A debounced caller (setFilter) closes over whatever `patch` identity
  // existed when its timer was scheduled. If a second URL change landed
  // before the timer fired and `patch` rebuilt `next` from a snapshot taken
  // at closure-creation time, that second change would be silently
  // discarded when the timer's stale `patch` finally ran.
  //
  // react-router-dom's own `setSearchParams` setter does not solve this by
  // itself: its returned function is a `useCallback` with `searchParams` in
  // its own dependency array (see node_modules/react-router's
  // `useSearchParams` — `useCallback((nextInit, opts) => ...nextInit(new
  // URLSearchParams(searchParams))..., [navigate, searchParams])`). Even
  // passing it a functional updater, the `prev` it hands back is whatever
  // `searchParams` was closed over when *that* `setSearchParams` instance
  // was created — not a live "current URL" the way React's own `useState`
  // updater guarantees. A quick check confirmed this the hard way: the
  // straightforward `setSearchParams((prev) => ...)` rewrite still failed
  // both regression tests below.
  //
  // `useNavigate()` does not have this problem: its identity depends on
  // route matches and pathname, not on the query string, so it stays
  // referentially stable across query-only navigations (confirmed against
  // the installed react-router-dom 7.18.2). Pairing it with a ref gives
  // `patch` one stable identity for the component's lifetime plus a
  // call-time read of the freshest URL state, no matter how long ago the
  // closure invoking it was created. The ref is resynced from `searchParams`
  // on every render (the source of truth for navigation `patch` didn't
  // cause — back/forward, a pasted link) and also written eagerly inside
  // `patch` itself (see below — needed so two patches landing in the same
  // tick still chain instead of both reading one stale snapshot).
  const searchParamsRef = useRef(searchParams);
  searchParamsRef.current = searchParams;

  const patch = useCallback(
    (changes: Record<string, string | null>, resetPage: boolean) => {
      const next = new URLSearchParams(searchParamsRef.current);
      Object.entries(changes).forEach(([key, value]) => {
        if (value === null) next.delete(key);
        else next.set(key, value);
      });
      // A narrowed result set with a stale offset paints an empty grid over a
      // non-zero total.
      if (resetPage) next.delete('page');
      // Write the ref eagerly, not just on the next render. Two debounced
      // keys can both come due in the same macrotask (one `advanceTimersByTime`
      // firing both timers back-to-back, with no React commit in between) —
      // without this, the second call would rebuild `next` from the same
      // pre-first-patch snapshot the first call read, and its write would
      // stomp the first one right back out.
      searchParamsRef.current = next;
      navigate(`?${next.toString()}`, { replace: true });
    },
    [navigate]
  );

  useEffect(() => {
    // A row deleted elsewhere (or a filter narrowing the set) can leave the
    // current offset past the end of the result — clamp back onto the last
    // real page rather than painting an empty grid over a non-zero total.
    if (total === undefined || total === 0) return;
    const lastPage = Math.max(0, Math.ceil(total / pageSize) - 1);
    if (page > lastPage) patch({ page: String(lastPage) }, false);
  }, [total, page, pageSize, patch]);

  // debounceKeys is typically an inline array literal at the call site too
  // (see filterKeysKey above) — key setFilter's memoisation on its stable
  // string form instead so callers passing a fresh array each render don't
  // get a new setFilter identity every render.
  const debounceKeysKey = debounceKeys.join(' ');

  // One timer per debounced key, not one shared timer — otherwise changing
  // key B (e.g. `notes`) would `clearTimeout` key A's (`search`) still-pending
  // write and it would never happen at all.
  const debounceTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const setFilter = useCallback(
    (key: string, value: string) => {
      if (!debounceKeys.includes(key)) {
        patch({ [key]: value }, true);
        return;
      }
      // Free-text filters (e.g. search) fire on every keystroke; debounce
      // rather than issuing a request per character.
      clearTimeout(debounceTimers.current[key]);
      debounceTimers.current[key] = setTimeout(() => patch({ [key]: value }, true), 300);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [debounceKeysKey, patch]
  );

  useEffect(
    () => () => Object.values(debounceTimers.current).forEach((timer) => clearTimeout(timer)),
    []
  );

  return {
    paginationModel: { page, pageSize },
    sortModel: [{ field: sort.sort_by, sort: sort.sort_dir }],
    onPaginationModelChange: useCallback(
      (model) => patch({ page: String(model.page), page_size: String(model.pageSize) }, false),
      [patch]
    ),
    onSortModelChange: useCallback(
      (model) => {
        const first = model[0];
        // The grid clears its sort model on a third header click; the endpoint
        // default is the honest answer, and it still travels with a direction.
        const resolved = resolveSort(endpoint, first?.field ?? null, first?.sort ?? null);
        patch({ sort_by: resolved.sort_by, sort_dir: resolved.sort_dir }, true);
      },
      [endpoint, patch]
    ),
    filters,
    setFilter,
  };
}
