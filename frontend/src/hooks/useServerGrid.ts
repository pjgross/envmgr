import { useCallback, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
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

export interface UseServerGridOptions {
  endpoint: EndpointKey;
  filterKeys: string[];
  onFetch: (params: ServerGridParams) => void;
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
}: UseServerGridOptions): ServerGrid {
  const [searchParams, setSearchParams] = useSearchParams();

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

  useEffect(() => {
    onFetch(params);
    // onFetch is a fresh dispatch closure on every render, and `params` is a
    // fresh object every render too; `paramsKey` is what decides whether a
    // refetch is warranted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramsKey]);

  const patch = useCallback(
    (changes: Record<string, string | null>, resetPage: boolean) => {
      const next = new URLSearchParams(searchParams);
      Object.entries(changes).forEach(([key, value]) => {
        if (value === null) next.delete(key);
        else next.set(key, value);
      });
      // A narrowed result set with a stale offset paints an empty grid over a
      // non-zero total.
      if (resetPage) next.delete('page');
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams]
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
    setFilter: useCallback((key, value) => patch({ [key]: value }, true), [patch]),
  };
}
