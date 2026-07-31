import whitelists from '../constants/sortWhitelists.json';

export type SortDir = 'asc' | 'desc';
export type EndpointKey = keyof typeof whitelists;

interface WhitelistEntry {
  sortable: string[];
  default: string;
  default_dir: SortDir;
}

export type ServerGridParams = {
  limit: number;
  offset: number;
  sort_by: string;
  sort_dir: SortDir;
} & Record<string, string | number>;

/** The pages' existing "no filter selected" values. */
const NO_FILTER = ['', 'all'];

/**
 * Reserved param names already set from the resolved page/sort. A filter key
 * colliding with one of these (e.g. a stray `sort_by` in a filters object)
 * would otherwise silently override the validated sort/paging values below.
 */
const RESERVED = new Set(['limit', 'offset', 'sort_by', 'sort_dir']);

function whitelistFor(endpoint: EndpointKey): WhitelistEntry {
  return whitelists[endpoint] as WhitelistEntry;
}

export function isSortable(endpoint: EndpointKey, field: string): boolean {
  return whitelistFor(endpoint).sortable.includes(field);
}

/**
 * Resolve a possibly-untrusted sort — typically straight out of a URL — into one
 * the server will accept. An unknown `sort_by` is a 422 by design, so it must be
 * replaced here rather than sent and handled.
 *
 * A direction is always returned. `sorting()` takes one endpoint-wide
 * `default_dir` used only when the client sends nothing, and four endpoints set
 * it to "desc" — so a first click on a header that omitted the direction would
 * render descending.
 */
export function resolveSort(
  endpoint: EndpointKey,
  sortBy: string | null,
  sortDir: string | null
): { sort_by: string; sort_dir: SortDir } {
  const wl = whitelistFor(endpoint);
  return {
    sort_by: sortBy && wl.sortable.includes(sortBy) ? sortBy : wl.default,
    sort_dir: sortDir === 'asc' || sortDir === 'desc' ? sortDir : wl.default_dir,
  };
}

export function buildParams(args: {
  endpoint: EndpointKey;
  page: number;
  pageSize: number;
  sortBy: string | null;
  sortDir: string | null;
  filters: Record<string, string>;
}): ServerGridParams {
  const { sort_by, sort_dir } = resolveSort(args.endpoint, args.sortBy, args.sortDir);
  const params: ServerGridParams = {
    limit: args.pageSize,
    offset: args.page * args.pageSize,
    sort_by,
    sort_dir,
  };
  Object.entries(args.filters).forEach(([key, value]) => {
    if (!RESERVED.has(key) && !NO_FILTER.includes(value)) params[key] = value;
  });
  return params;
}
