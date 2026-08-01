import { useEffect, useState } from 'react';
import { systemService } from '../services/systemService';
import type { SystemResponse } from '../types/system';

// `GET /systems/` defaults to 500 server-side (backend `DEFAULT_LIMIT`);
// asked for explicitly so the number a picker can see is visible at this
// call site rather than implicit in the endpoint.
const LIMIT = 500;

/**
 * Every system, for a picker.
 *
 * NOT `state.system.systems`: a later task converts `SystemCatalog` to
 * server-side paging, at which point that slice becomes its current
 * filtered page rather than every system. Six components need this; the
 * shared hook exists so a seventh is not written by copy-paste.
 *
 * `systemService.listSystems` still returns a bare array — no total count —
 * so unlike its `useAllEnvironments`/`useAllHosts` siblings this hook has no
 * honest way to detect truncation yet. `truncated` is hardcoded `false`
 * until that task widens the service to `Paged<SystemResponse>`; do not
 * read `false` here as a claim the list is complete.
 */
export function useAllSystems(): {
  systems: SystemResponse[];
  loading: boolean;
  truncated: boolean;
} {
  const [systems, setSystems] = useState<SystemResponse[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    systemService
      .listSystems({ limit: LIMIT })
      .then((rows) => {
        setSystems(rows);
      })
      .catch(() => {
        setSystems([]);
      })
      .finally(() => setLoading(false));
  }, []);

  // Hardcoded, not computed: `listSystems` returns a bare array with no
  // total, so there is nothing honest to compare `systems.length` against.
  // A `systems.length === LIMIT` proxy was rejected for the same reason it
  // was rejected in `useAllEnvironments`/`useAllHosts` — wrong the moment a
  // tenant's count happens to land exactly on the limit.
  const truncated = false;

  return { systems, loading, truncated };
}
