import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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

/**
 * `DataTable`'s `pageSizeOptions` is the fixed set `[10, 25, 50, 100]`. A
 * `page_size` that's a valid integer 1-100 but not one of those (e.g. a
 * hand-edited `?page_size=7`) still produces a valid request, but MUI logs
 * an out-of-range console warning and renders a blank page-size select.
 */
const ALLOWED_PAGE_SIZES = [10, 25, 50, 100];
const clampPageSize = (raw: string | null): number => {
  const n = clampInt(raw, DEFAULT_PAGE_SIZE, 1, 100);
  return ALLOWED_PAGE_SIZES.includes(n) ? n : DEFAULT_PAGE_SIZE;
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
  /**
   * Filter keys whose changes should be debounced — free-text inputs.
   *
   * This list does double duty: it is also passed straight through to
   * `buildParams` as `textKeys`, the set of keys for which `'all'` is a real
   * search term rather than a select's "no selection" sentinel (see
   * `serverGridParams.ts`). A text filter deliberately left out of this list
   * — e.g. one that only applies on Enter/blur for a heavy endpoint, rather
   * than on every keystroke — gets no `'all'` exemption either, and
   * re-inherits the exact bug this list exists to fix: typing `all` returns
   * unfiltered results while the box still reads "all".
   *
   * INVARIANT: every key listed here must also appear in `filterKeys`.
   * `filters` (below) is built from `filterKeys` alone, so a key present
   * only in `debounceKeys` is written to the URL by `setFilter` but never
   * read back — the URL shows `?search=foo` beside a grid that isn't
   * actually filtered. Violations are warned about in dev; see the
   * `import.meta.env.DEV` check below.
   */
  debounceKeys?: string[];
  /** Latest known total, used to clamp an offset that has run past the end. */
  total?: number;
  /**
   * True when we cannot safely assume `total` reflects the current server state.
   * Clamping the page number against a potentially-stale `total` would rewrite a
   * legitimate deep link (`?page=8`) back to page 0 before that page's own
   * response arrives.
   */
  totalPending?: boolean;
}

export interface ServerGrid {
  paginationModel: { page: number; pageSize: number };
  sortModel: { field: string; sort: SortDir }[];
  onPaginationModelChange: (model: { page: number; pageSize: number }) => void;
  onSortModelChange: (model: { field: string; sort?: SortDir | null }[]) => void;
  filters: Record<string, string>;
  setFilter: (key: string, value: string) => void;
  /** Re-issue the current query — after a create or delete changed the set. */
  refetch: () => void;
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
  totalPending,
}: UseServerGridOptions): ServerGrid {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const page = clampInt(searchParams.get('page'), 0, 0, Number.MAX_SAFE_INTEGER);
  const pageSize = clampPageSize(searchParams.get('page_size'));
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
  // debounceKeys is typically an inline array literal at the call site too
  // (see filterKeysKey above) — key setFilter's memoisation on its stable
  // string form instead so callers passing a fresh array each render don't
  // get a new setFilter identity every render.
  const debounceKeysKey = debounceKeys.join(' ');

  // debounceKeys does double duty as serverGridParams' textKeys (see the
  // JSDoc on UseServerGridOptions.debounceKeys). A key present only in
  // debounceKeys is written to the URL by setFilter but never read back into
  // `filters`, which is built from filterKeys alone — a silent, easy-to-copy
  // mistake across the eight upcoming page conversions. Warn, don't throw: a
  // dev console warning must not take a page down.
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    const missing = debounceKeys.filter((key) => !filterKeys.includes(key));
    if (missing.length > 0) {
      console.warn(
        `useServerGrid: debounceKeys ${JSON.stringify(missing)} missing from filterKeys — ` +
          'these keys are written to the URL by setFilter but never read back into `filters`, ' +
          "and lose their 'all' exemption from serverGridParams."
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKeysKey, debounceKeysKey]);

  const filters = useMemo(() => {
    const out: Record<string, string> = {};
    filterKeys.forEach((key) => {
      const value = searchParams.get(key);
      if (value !== null) out[key] = value;
    });
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, filterKeysKey]);

  // Debounced text filters (search boxes) need to show every keystroke
  // immediately even though the URL write behind them is delayed 300ms.
  // `filters` above is a straight readout of the URL, so binding an <input>
  // to it directly re-renders the box back to the pre-keystroke value on
  // every render until the debounce finally lands — the next real keystroke
  // then replaces the box's contents instead of appending to them (a
  // controlled input always displays exactly its `value` prop). `drafts`
  // holds the in-progress text for debounced keys only; `setFilter` writes
  // it synchronously so typing never waits on the URL, and `displayFilters`
  // below overlays it on top of `filters` for the consumer-facing API.
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  // The exact query string this hook's own `patch` last wrote (a debounce
  // landing, or any other setFilter/sort/page write) — as opposed to
  // `undefined` covering both external navigation (Back/Forward, a pasted
  // link) and "no patch since we last checked". Set eagerly inside `patch`,
  // right before `navigate`, and consumed by the effect the next time
  // `searchParams` changes.
  //
  // This holds the written *string*, not a boolean "a patch just happened"
  // flag, because a patch that writes a query string identical to the
  // current one never fires the reconciliation effect at all: `searchParams`
  // is memoised on `location.search` (see the JSDoc on `patch` below), so an
  // unchanged string produces no new object and the effect's dependency
  // never changes. A boolean set right before that `navigate` call would
  // then sit `true` indefinitely — through any number of further no-op
  // patches — until some *later*, genuinely external navigation finally
  // changes `searchParams` and reads it, wrongly treating that external
  // change as self-caused: a stale draft would survive and its pending
  // debounce timer would go uncancelled, so it fires later and rewrites the
  // URL of whatever view the user has since navigated to. Comparing the
  // recorded string against the live `searchParams.toString()` instead is
  // self-correcting regardless of how many effect-skipping no-ops happen in
  // between: a no-op patch records a string that (by definition) already
  // equals the current URL, so it's still "correct" the next time it's
  // read, and the first navigation that actually changes the query string —
  // self- or externally-caused — is judged against what really changed, not
  // against a leftover flag from an unrelated write.
  const patchedSearchRef = useRef<string | null>(null);

  // One timer per debounced key, not one shared timer — otherwise changing
  // key B (e.g. `notes`) would `clearTimeout` key A's (`search`) still-pending
  // write and it would never happen at all. Declared up here (rather than
  // beside `setFilter` below) so the reconciliation effect can also reach it.
  const debounceTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  // Reconciles `drafts` against the URL every time the URL actually changes.
  //
  // - Self-initiated (a patch this hook made, most commonly a debounce
  //   landing): drop any draft entry whose value now matches the committed
  //   URL — it has converged, `filters` alone is enough from here. A draft
  //   for a *different* still-pending key survives untouched.
  // - External (the flag was never set — Back/Forward, a pasted link, any
  //   navigation this hook did not cause): abandon every draft outright, so
  //   the input immediately reflects the new URL. This is deliberately not
  //   an equality check — the new URL and the old draft coincidentally
  //   holding the same text is not the same thing as the user's edit having
  //   been accepted, and an equality check would still show a stale draft
  //   whenever the new URL happens to differ from it (e.g. it omits the key
  //   entirely) but a *later* per-key diff never notices because the value
  //   never changes again. Abandoning a draft this way also cancels its
  //   pending debounce timer — left alone, that timer would still fire later
  //   with the stale pre-navigation text and silently write it back into the
  //   URL (and the box) of whatever view the user has since navigated to.
  useEffect(() => {
    const wasSelfPatched = patchedSearchRef.current === searchParams.toString();
    patchedSearchRef.current = null;
    setDrafts((current) => {
      if (Object.keys(current).length === 0) return current;
      if (!wasSelfPatched) {
        Object.keys(current).forEach((key) => clearTimeout(debounceTimers.current[key]));
        return {};
      }
      let changed = false;
      const next: Record<string, string> = {};
      Object.entries(current).forEach(([key, value]) => {
        if (filters[key] === value) {
          changed = true;
          return;
        }
        next[key] = value;
      });
      return changed ? next : current;
    });
  }, [searchParams, filters]);

  // The consumer-facing `filters`: the URL, with any in-progress draft text
  // overlaid on top. Only ever differs from `filters` for debounced keys
  // mid-keystroke, so non-debounced controls (selects, dates) are unaffected
  // — and when there is no pending draft, this returns `filters` itself
  // rather than a new object, preserving referential stability across
  // renders that change nothing.
  const displayFilters = useMemo(
    () => (Object.keys(drafts).length === 0 ? filters : { ...filters, ...drafts }),
    [filters, drafts]
  );

  const params = useMemo(
    () =>
      buildParams({
        endpoint,
        page,
        pageSize,
        sortBy: sort.sort_by,
        sortDir: sort.sort_dir,
        filters,
        textKeys: debounceKeys,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [endpoint, page, pageSize, sort.sort_by, sort.sort_dir, filters, debounceKeysKey]
  );

  // Key the fetch effect on the *resolved* request, not a hand-maintained
  // list of raw URL values — that list previously omitted `endpoint` (an
  // endpoint change fetched nothing) and treated e.g. a filter moving into
  // or out of the "all"/"" sentinel as a change even though `buildParams`
  // drops that value either way, issuing a duplicate byte-identical GET.
  const paramsKey = JSON.stringify(params);

  const inFlight = useRef<Abortable | void>();

  // The fetch effect is keyed on the resolved params, so an identical query
  // cannot re-run on its own. A nonce gives callers an explicit way to ask
  // for one without inventing a fake param change.
  const [refetchNonce, setRefetchNonce] = useState(0);
  const refetch = useCallback(() => setRefetchNonce((n) => n + 1), []);

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
  }, [paramsKey, refetchNonce]);

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
      // Record the exact string being written, before `navigate`, so the
      // reconciliation effect above can compare it against whatever
      // `searchParams` turns out to be next time it runs — see the JSDoc on
      // `patchedSearchRef` for why a plain "a patch just happened" boolean
      // isn't safe here (a no-op write never triggers that effect run at
      // all).
      patchedSearchRef.current = next.toString();
      navigate(`?${next.toString()}`, { replace: true });
    },
    [navigate]
  );

  useEffect(() => {
    // A row deleted elsewhere (or a filter narrowing the set) can leave the
    // current offset past the end of the result — clamp back onto the last
    // real page rather than painting an empty grid over a non-zero total.
    if (totalPending || total === undefined || total === 0) return;
    const lastPage = Math.max(0, Math.ceil(total / pageSize) - 1);
    if (page > lastPage) patch({ page: String(lastPage) }, false);
  }, [totalPending, total, page, pageSize, patch]);

  const setFilter = useCallback(
    (key: string, value: string) => {
      if (!debounceKeys.includes(key)) {
        patch({ [key]: value }, true);
        return;
      }
      // Free-text filters (e.g. search) fire on every keystroke. Show the
      // keystroke immediately via `drafts` — the controlled input must never
      // wait on the URL, or the next keystroke replaces rather than appends
      // to it (see `displayFilters` above) — but still debounce the URL
      // write itself rather than issuing a request per character.
      setDrafts((current) => ({ ...current, [key]: value }));
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
    filters: displayFilters,
    setFilter,
    refetch,
  };
}
