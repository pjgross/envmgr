import { systemService } from '../services/systemService';
import { useSharedList } from './useSharedList';
import type { SystemResponse } from '../types/system';

// `GET /systems/` defaults to 500 server-side (backend `DEFAULT_LIMIT`);
// asked for explicitly so the number a picker can see is visible at this
// call site rather than implicit in the endpoint.
const LIMIT = 500;

// Module-level, so `useSharedList` can safely keep it out of its effect deps.
const load = () => systemService.listSystems({ limit: LIMIT });

/**
 * Every system, for a picker.
 *
 * NOT `state.system.systems`: since the C3 conversion that slice is
 * `SystemCatalog`'s current filtered page rather than every system. Seven
 * components need this; the shared hook exists so an eighth is not written by
 * copy-paste.
 *
 * Consumers mounting in the same commit share one request — see
 * `useSharedList`, which coalesces in-flight fetches without caching them.
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
  const { rows, loading, truncated } = useSharedList<SystemResponse>('systems', load);
  return { systems: rows, loading, truncated };
}
