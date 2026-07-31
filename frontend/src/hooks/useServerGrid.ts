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

  const page = Number(searchParams.get('page') ?? 0);
  const pageSize = Number(searchParams.get('page_size') ?? DEFAULT_PAGE_SIZE);
  const rawSortBy = searchParams.get('sort_by');
  const rawSortDir = searchParams.get('sort_dir');
  const sort = resolveSort(endpoint, rawSortBy, rawSortDir);

  const filters = useMemo(() => {
    const out: Record<string, string> = {};
    filterKeys.forEach((key) => {
      const value = searchParams.get(key);
      if (value !== null) out[key] = value;
    });
    return out;
  }, [searchParams, filterKeys]);

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

  // The fetch effect keys on the *raw* URL values, not the resolved/validated
  // `params` object. An omitted `sort_by` and an explicit `sort_by=<default>`
  // resolve to the same request but are different URLs — e.g. the grid
  // clearing its sort model writes the default back explicitly — and each
  // still represents a distinct user action that should trigger its own
  // fetch. Keying on resolved output instead would silently swallow that
  // fetch whenever the resolved value happened to already equal the default.
  const rawKey = JSON.stringify([
    page,
    pageSize,
    rawSortBy,
    rawSortDir,
    filterKeys.map((key) => searchParams.get(key)),
  ]);

  useEffect(() => {
    onFetch(params);
    // onFetch is a fresh dispatch closure on every render, and `params` is a
    // fresh object every render too; `rawKey` — derived straight from the URL
    // — is what decides whether a refetch is warranted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rawKey]);

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
