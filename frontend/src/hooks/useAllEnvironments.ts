import { environmentService } from '../services/environmentService';
import { useSharedList } from './useSharedList';
import type { EnvironmentResponse } from '../types/environment';

// `GET /environments/` defaults to 500 server-side; asked for explicitly so
// the number a picker can see is visible at this call site rather than
// implicit in the endpoint.
const LIMIT = 500;

// Module-level, so `useSharedList` can safely keep it out of its effect deps.
const load = () => environmentService.listEnvironments({ limit: LIMIT });

/**
 * Every environment, for a picker.
 *
 * NOT `state.environment.environments`: since the C3 conversion that slice is
 * `EnvironmentList`'s current filtered page, so a dropdown reading it would
 * silently offer a subset. Nine components needed this; the shared hook exists
 * so a tenth is not written by copy-paste.
 *
 * Consumers mounting in the same commit share one request — see
 * `useSharedList`, which coalesces in-flight fetches without caching them.
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
  const { rows, loading, truncated } = useSharedList<EnvironmentResponse>('environments', load);
  return { environments: rows, loading, truncated };
}
