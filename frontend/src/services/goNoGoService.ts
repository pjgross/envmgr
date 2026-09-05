import api from './api';
import type { Paged } from '../types/pagination';
import type {
  GoNoGoConditionRead,
  GoNoGoDecisionCreate,
  GoNoGoDecisionRead,
  GoNoGoPerspectiveCreate,
  GoNoGoPerspectiveRead,
  GoNoGoPerspectiveUpdate,
} from '../types/goNoGo';

// GET /releases/{id}/go-no-go is a reduced page contract (default 50, max
// 200), not the shared 500/1000 default — go_no_go_service.reads_for_
// decisions does per-row work after the query, loading every signoff/
// condition on the page. `sort_by` is whitelisted server-side to
// `decided_at`/`outcome`; an unknown value 422s rather than silently
// falling back. `params` is passed through untyped, same shape
// `pirService.listActions` uses, so a caller can send `limit`/`offset`/
// `sort_by`/`sort_dir` without this service re-declaring each one.
export const goNoGoService = {
  list: (
    releaseId: number,
    params: Record<string, unknown> = {}
  ): Promise<Paged<GoNoGoDecisionRead>> =>
    api.get<GoNoGoDecisionRead[]>(`/releases/${releaseId}/go-no-go`, { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),

  // The readiness snapshot is frozen SERVER-SIDE — this payload carries no
  // snapshot fields, matching GoNoGoDecisionCreate exactly.
  record: (releaseId: number, data: GoNoGoDecisionCreate): Promise<GoNoGoDecisionRead> =>
    api.post<GoNoGoDecisionRead>(`/releases/${releaseId}/go-no-go`, data).then((r) => r.data),

  // The only mutation an append-only decision allows: close (met=true) or
  // reopen (met=false) one condition. Addressed directly by its own id, no
  // /releases prefix — see app/api/v1/go_no_go.py.
  closeCondition: (conditionId: number, met: boolean): Promise<GoNoGoConditionRead> =>
    api
      .patch<GoNoGoConditionRead>(`/go-no-go-conditions/${conditionId}`, { met })
      .then((r) => r.data),

  // Reads are open to any tenant member (writes are Admin-only — see
  // app/api/v1/go_no_go.py's perspectives_router; no write path is needed by
  // this task).
  listPerspectives: (includeInactive = true): Promise<GoNoGoPerspectiveRead[]> =>
    api
      .get<GoNoGoPerspectiveRead[]>('/tenant/go-no-go-perspectives', {
        params: { include_inactive: includeInactive },
      })
      .then((r) => r.data),

  // Admin-only server-side (require_tenant_admin) — see
  // app/api/v1/go_no_go.py's perspectives_router. A duplicate name within
  // the tenant is a 409, not a 500 (the service pre-checks); there is no
  // delete — a perspective is retired via `is_active: false` through update.
  createPerspective: (data: GoNoGoPerspectiveCreate): Promise<GoNoGoPerspectiveRead> =>
    api
      .post<GoNoGoPerspectiveRead>('/tenant/go-no-go-perspectives', data)
      .then((r) => r.data),

  updatePerspective: (
    id: number,
    data: GoNoGoPerspectiveUpdate
  ): Promise<GoNoGoPerspectiveRead> =>
    api
      .patch<GoNoGoPerspectiveRead>(`/tenant/go-no-go-perspectives/${id}`, data)
      .then((r) => r.data),
};
