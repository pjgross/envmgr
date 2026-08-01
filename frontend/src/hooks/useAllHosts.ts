import { useEffect, useState } from 'react';
import { infrastructureComponentService } from '../services/infrastructureComponentService';
import type { InfrastructureComponentResponse } from '../types/infrastructureComponent';

// `GET /infrastructure-components/` defaults to 500 server-side; asked for
// explicitly so the number a picker can see is visible at this call site
// rather than implicit in the endpoint.
const LIMIT = 500;

/**
 * Every infrastructure component ("host"), for a picker.
 *
 * NOT `state.infrastructureComponent.components`: once
 * `InfrastructureComponentList` moves to server-side paging that slice
 * becomes its current filtered page, so a dropdown reading it would
 * silently offer a subset. Four components need this; the shared hook
 * exists so a fifth is not written by copy-paste.
 *
 * `truncated` is true when the server has more than we asked for — a picker
 * that is quietly missing options is the bug this programme exists to remove,
 * so callers can say so rather than pretend the list is complete.
 */
export function useAllHosts(): {
  hosts: InfrastructureComponentResponse[];
  loading: boolean;
  truncated: boolean;
} {
  const [hosts, setHosts] = useState<InfrastructureComponentResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    infrastructureComponentService
      .listComponents({ limit: LIMIT })
      .then(({ rows, total }) => {
        setHosts(rows);
        setTotal(total);
      })
      .catch(() => {
        setHosts([]);
        setTotal(0);
      })
      .finally(() => setLoading(false));
  }, []);

  // Honest, not a proxy: `hosts.length === LIMIT` would be wrong the moment
  // a tenant's count happens to land exactly on the limit.
  const truncated = hosts.length < total;

  return { hosts, loading, truncated };
}
