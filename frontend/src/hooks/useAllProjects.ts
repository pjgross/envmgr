import { projectService } from '../services/projectService';
import { useSharedList } from './useSharedList';
import type { ProjectResponse } from '../types/project';

// `GET /projects` defaults to 500 server-side (backend `DEFAULT_LIMIT`);
// asked for explicitly so the number a picker can see is visible at this
// call site rather than implicit in the endpoint.
const LIMIT = 500;

// Module-level, so `useSharedList` can safely keep it out of its effect deps.
// Archived projects must not be offered here — every consumer of this hook is
// a picker or a filter, never a form preserving an existing archived value
// (those carve out the stored id separately, the way ReleaseForm's Owning
// project select does).
const load = () => projectService.listProjects({ is_active: true, limit: LIMIT });

/**
 * Every active project, for a picker or filter.
 *
 * NOT `state.project.projects`: that slice is written by whichever page last
 * dispatched `fetchProjects`, so a second consumer mounted in the same commit
 * (BookingList renders BookingForm's dialog unconditionally) would silently
 * share — and clobber — a page-scoped fetch, and past 500 active projects a
 * project would be silently missing from every picker with no way to tell.
 * Four consumers needed this; the shared hook exists so a fifth is not
 * written by copy-paste.
 *
 * Consumers mounting in the same commit share one request — see
 * `useSharedList`, which coalesces in-flight fetches without caching them.
 *
 * `truncated` is true when the server has more than we asked for — a picker
 * that is quietly missing options is the bug this programme exists to remove,
 * so callers can say so rather than pretend the list is complete.
 */
export function useAllProjects(): {
  projects: ProjectResponse[];
  loading: boolean;
  truncated: boolean;
} {
  const { rows, loading, truncated } = useSharedList<ProjectResponse>('projects', load);
  return { projects: rows, loading, truncated };
}
