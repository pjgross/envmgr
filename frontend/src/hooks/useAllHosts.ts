import { infrastructureComponentService } from '../services/infrastructureComponentService';
import { useSharedList } from './useSharedList';
import type { InfrastructureComponentResponse } from '../types/infrastructureComponent';

// `GET /infrastructure-components/` defaults to 500 server-side; asked for
// explicitly so the number a picker can see is visible at this call site
// rather than implicit in the endpoint.
const LIMIT = 500;

// Module-level, so `useSharedList` can safely keep it out of its effect deps.
const load = () => infrastructureComponentService.listComponents({ limit: LIMIT });

/**
 * Every infrastructure component ("host"), for a picker.
 *
 * NOT `state.infrastructureComponent.components`: since the C3 conversion that
 * slice is `InfrastructureComponentList`'s current filtered page, so a
 * dropdown reading it would silently offer a subset. Four components need
 * this; the shared hook exists so a fifth is not written by copy-paste.
 *
 * Consumers mounting in the same commit share one request — `ChangeRequestList`
 * renders `ChangeRequestForm` unconditionally, so this page used to issue two
 * identical GETs. See `useSharedList`, which coalesces in-flight fetches
 * without caching them.
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
  const { rows, loading, truncated } = useSharedList<InfrastructureComponentResponse>(
    'hosts',
    load
  );
  return { hosts: rows, loading, truncated };
}
