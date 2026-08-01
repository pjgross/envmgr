import { useEffect, useState } from 'react';
import { environmentService } from '../services/environmentService';
import type { EnvironmentResponse } from '../types/environment';

// `GET /environments/` defaults to 500 server-side; asked for explicitly so
// the number a picker can see is visible at this call site rather than
// implicit in the endpoint.
const LIMIT = 500;

/**
 * Every environment, for a picker.
 *
 * NOT `state.environment.environments`: since the C3 conversion that slice is
 * `EnvironmentList`'s current filtered page, so a dropdown reading it would
 * silently offer a subset. Nine components needed this; the shared hook exists
 * so a tenth is not written by copy-paste.
 *
 * `truncated` is true when the server has more than we asked for — a picker
 * that is quietly missing options is the bug this programme exists to remove,
 * so callers can say so rather than pretend the list is complete.
 */
export function useAllEnvironments(): {
  environments: EnvironmentResponse[];
  loading: boolean;
  truncated: boolean;
} {
  const [environments, setEnvironments] = useState<EnvironmentResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    environmentService
      .listEnvironments({ limit: LIMIT })
      .then(({ rows, total }) => {
        setEnvironments(rows);
        setTotal(total);
      })
      .catch(() => {
        setEnvironments([]);
        setTotal(0);
      })
      .finally(() => setLoading(false));
  }, []);

  // Honest, not a proxy: `environments.length === LIMIT` would be wrong the
  // moment a tenant's count happens to land exactly on the limit.
  const truncated = environments.length < total;

  return { environments, loading, truncated };
}
