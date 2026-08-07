import { environmentGroupService } from '../services/environmentGroupService';
import { useSharedList } from './useSharedList';
import type { EnvironmentGroupResponse } from '../types/environmentGroup';

// `GET /environment-groups` defaults to 500 server-side (backend
// `DEFAULT_LIMIT`); asked for explicitly so the number a picker can see is
// visible at this call site rather than implicit in the endpoint.
const LIMIT = 500;

// Module-level, so `useSharedList` can safely keep it out of its effect deps.
// Inactive groups must not be offered here — every consumer of this hook is
// a picker or a filter, never a form preserving an existing archived value.
const load = () => environmentGroupService.listGroups({ is_active: true, limit: LIMIT });

/**
 * Every active environment group, for a picker or filter.
 *
 * NOT `state.environmentGroup.groups`: that slice is written by whichever
 * page last dispatched `fetchEnvironmentGroups`, so a second consumer
 * mounted in the same commit would silently share — and clobber — a
 * page-scoped fetch, and past 500 active groups a group would be silently
 * missing from every picker with no way to tell.
 *
 * Consumers mounting in the same commit share one request — see
 * `useSharedList`, which coalesces in-flight requests without caching them.
 *
 * `truncated` is true when the server has more than we asked for — a picker
 * that is quietly missing options is the bug this programme exists to remove,
 * so callers can say so rather than pretend the list is complete.
 */
export function useAllEnvironmentGroups(): {
  groups: EnvironmentGroupResponse[];
  loading: boolean;
  truncated: boolean;
} {
  const { rows, loading, truncated } = useSharedList<EnvironmentGroupResponse>(
    'environmentGroups',
    load
  );
  return { groups: rows, loading, truncated };
}
