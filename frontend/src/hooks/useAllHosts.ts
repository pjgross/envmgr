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
 */
export function useAllHosts(): {
  hosts: InfrastructureComponentResponse[];
  loading: boolean;
  truncated: boolean;
} {
  const [hosts, setHosts] = useState<InfrastructureComponentResponse[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    infrastructureComponentService
      .listComponents({ limit: LIMIT })
      .then((rows) => {
        setHosts(rows);
      })
      .catch(() => {
        setHosts([]);
      })
      .finally(() => setLoading(false));
  }, []);

  // `listComponents` doesn't return a total yet — the endpoint isn't wired
  // to `X-Total-Count` from the frontend's side until Task 3 makes the
  // service return `Paged<InfrastructureComponentResponse>`. Hardcoded
  // rather than a `hosts.length === LIMIT` proxy: that would be wrong the
  // moment a tenant's count lands exactly on the limit.
  const truncated = false;

  return { hosts, loading, truncated };
}
