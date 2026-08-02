import { useEffect, useState } from 'react';

/**
 * Shared machinery behind `useAllSystems` / `useAllEnvironments` / `useAllHosts`.
 *
 * Those three hooks were byte-for-byte identical apart from the service they
 * called, and each mounted consumer fired its own request. `ChangeRequestList`
 * renders `ChangeRequestForm` unconditionally (the dialog takes `open` as a
 * prop rather than being conditionally mounted), so both call `useAllHosts`
 * in the same commit and the page issued two identical GETs — likewise
 * environments.
 *
 * **This coalesces in-flight requests; it is deliberately not a cache.** The
 * map entry is removed the moment the request settles, so a component mounting
 * later always re-fetches. A picker that keeps serving a list from before the
 * user created a new row is precisely the class of bug this programme has been
 * removing — and one that was reported here in exactly that shape — so the
 * only thing collapsed is requests that overlap in time, which is the actual
 * defect.
 */
type ListResult<T> = { rows: T[]; total: number };

/** Empty stands in for a failed fetch — see the note on the catch below. */
const EMPTY: ListResult<never> = { rows: [], total: 0 };

/**
 * Keyed by the caller's `key`, erased on settle.
 *
 * The stored promise **never rejects**: the failure is folded into its value at
 * the point of creation, where exactly one handler is guaranteed to exist. If
 * the shared promise could reject, whether every subscriber had attached a
 * handler before it settled would be a timing question, and losing that race
 * is an unhandled rejection. Attaching the handler once, at creation, removes
 * the race rather than making it unlikely.
 */
const inFlight = new Map<string, Promise<ListResult<never>>>();

export interface SharedList<T> {
  rows: T[];
  loading: boolean;
  /**
   * True when the server holds more rows than were fetched. Honest, not a
   * proxy: `rows.length === LIMIT` would be wrong the moment a tenant's count
   * happens to land exactly on the limit.
   */
  truncated: boolean;
}

/**
 * @param key    identifies the request; two consumers sharing a key share a fetch
 * @param load   must be a module-level constant, not an inline closure — it is
 *               intentionally not an effect dependency, since a fresh closure
 *               each render would re-fire the fetch on every render
 */
export function useSharedList<T>(key: string, load: () => Promise<ListResult<T>>): SharedList<T> {
  const [rows, setRows] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    let request = inFlight.get(key) as Promise<ListResult<T>> | undefined;
    if (!request) {
      request = load()
        // A failed fetch reads as an empty list rather than throwing: a picker
        // with no options is recoverable, an unhandled rejection is not. Doing
        // it here rather than per-subscriber is what makes the shared promise
        // safe to hand out — see the note on `inFlight`.
        .catch(() => EMPTY as ListResult<T>)
        // The entry must clear once, when the request settles, not once per
        // subscriber. It clears on failure too, so one failed fetch does not
        // poison the key for the rest of the session.
        .finally(() => {
          inFlight.delete(key);
        });
      inFlight.set(key, request as Promise<ListResult<never>>);
    }

    request.then((result) => {
      if (cancelled) return;
      setRows(result.rows);
      setTotal(result.total);
      setLoading(false);
    });

    return () => {
      cancelled = true;
    };
    // `load` is excluded deliberately — see the JSDoc above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { rows, loading, truncated: rows.length < total };
}
