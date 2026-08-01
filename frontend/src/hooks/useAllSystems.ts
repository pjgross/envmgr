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
 * `truncated` is true when the server has more than we asked for — a picker
 * that is quietly missing options is the bug this programme exists to remove,
 * so callers can say so rather than pretend the list is complete.
 */
export function useAllSystems(): {
  systems: SystemResponse[];
  loading: boolean;
  truncated: boolean;
} {
  const [systems, setSystems] = useState<SystemResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    systemService
      .listSystems({ limit: LIMIT })
      .then(({ rows, total }) => {
        setSystems(rows);
        setTotal(total);
      })
      .catch(() => {
        setSystems([]);
        setTotal(0);
      })
      .finally(() => setLoading(false));
  }, []);

  // Honest, not a proxy: `systems.length === LIMIT` would be wrong the
  // moment a tenant's count happens to land exactly on the limit.
  const truncated = systems.length < total;

  return { systems, loading, truncated };
}
