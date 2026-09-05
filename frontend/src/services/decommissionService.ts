import api from './api';
import type {
  Attestation,
  AttestationCreate,
  CancelRequest,
  Decommission,
  DecommissionCreate,
  DecommissionState,
  DecommissionStep,
  DecommissionStepWrite,
  DecommissionWorklistRow,
  ExtensionDecision,
  ExtensionRequest,
  TeardownResult,
} from '../types/decommission';
import type { Paged } from '../types/pagination';

export const decommissionService = {
  // GET /environments/{id}/decommission — the live record, or the most
  // recent terminal one when there is none, or null. Never 404 for "this
  // environment has never been decommissioned" — null IS the ordinary
  // answer, per decommissions.py's module docstring; the panel renders its
  // initiate control from it.
  getForEnvironment: (environmentId: number): Promise<Decommission | null> =>
    api.get(`/environments/${environmentId}/decommission`).then((r) => r.data),

  initiate: (environmentId: number, data: DecommissionCreate): Promise<Decommission> =>
    api.post(`/environments/${environmentId}/decommission`, data).then((r) => r.data),

  requestExtension: (decommissionId: number, data: ExtensionRequest): Promise<Decommission> =>
    api.post(`/decommissions/${decommissionId}/extension`, data).then((r) => r.data),

  decideExtension: (decommissionId: number, data: ExtensionDecision): Promise<Decommission> =>
    api.post(`/decommissions/${decommissionId}/extension/decision`, data).then((r) => r.data),

  signAttestation: (decommissionId: number, data: AttestationCreate): Promise<Attestation> =>
    api.post(`/decommissions/${decommissionId}/attestations`, data).then((r) => r.data),

  // THE ONE ACTING ROUTE. No body — decommissions.py's route takes only the
  // path id.
  tearDown: (decommissionId: number): Promise<TeardownResult> =>
    api.post(`/decommissions/${decommissionId}/teardown`).then((r) => r.data),

  cancel: (decommissionId: number, data: CancelRequest): Promise<Decommission> =>
    api.post(`/decommissions/${decommissionId}/cancel`, data).then((r) => r.data),

  // GET /tenant/decommission-steps — the tenant's checklist vocabulary. A
  // plain array, not paginated: this is tenant-configured (`environment_tier`
  // precedent), small by construction, not a growth-bearing list. Defaults to
  // `active_only=true` because the panel's checklist renders what a
  // decommission must satisfy TODAY — a retired step stops gating, per
  // `missing_required_steps`' own docstring.
  listSteps: (activeOnly = true): Promise<DecommissionStep[]> =>
    api
      .get<DecommissionStep[]>('/tenant/decommission-steps', {
        params: { active_only: activeOnly },
      })
      .then((r) => r.data),

  // Write CRUD for the checklist vocabulary — Task 14's admin panel. All
  // three are `require_tenant_admin()` on the backend; the panel gates its
  // own controls to match rather than relying on this call site to refuse.
  createStep: (data: DecommissionStepWrite): Promise<DecommissionStep> =>
    api.post('/tenant/decommission-steps', data).then((r) => r.data),

  // PATCH takes the SAME shape as POST (`DecommissionStepWrite` on the
  // backend, not a partial `...Update`) — every field travels on every edit.
  updateStep: (id: number, data: DecommissionStepWrite): Promise<DecommissionStep> =>
    api.patch(`/tenant/decommission-steps/${id}`, data).then((r) => r.data),

  // Soft delete — deliberately never refused, even if a live decommission
  // still references the key (see environment_lifecycle_policy_service.delete_step).
  // A retired step just stops gating new teardowns.
  deleteStep: (id: number): Promise<void> =>
    api.delete(`/tenant/decommission-steps/${id}`).then(() => undefined),

  // The worklist: every decommission this tenant can see, live and terminal
  // alike (GET /decommissions, extensions_router's own prefix).
  //
  // `state` has deliberately no 'all' value on the wire — omission is the
  // "no selection" sentinel (decommissions.py: "OMIT for everything — there
  // is deliberately no 'all' value"). Callers spell "no selection" `any`,
  // never `all` — that's buildParams' own sentinel, and A3, A4, B2 and B4
  // each collided with it in turn.
  listWorklist: (params?: {
    state?: DecommissionState;
    /**
     * `true`: only decommissions on an environment the caller operates —
     * the same membership rule `/me/work`'s decommissions queue uses. OMIT
     * for the whole tenant's estate (this endpoint's original behaviour).
     * Added for PR 3's dashboard fix wave, finding 6 — `/decommissions` did
     * not expose the narrowing spec §5's amendment said it would.
     */
    mine?: boolean;
    limit?: number;
    offset?: number;
    sort_by?: 'scheduled_teardown_at' | 'warned_at' | 'environment';
    sort_dir?: 'asc' | 'desc';
  }): Promise<Paged<DecommissionWorklistRow>> =>
    api.get<DecommissionWorklistRow[]>('/decommissions', { params }).then((r) => ({
      rows: r.data,
      // The server's total for the FILTERED set, never rows.length (that's
      // one windowed page) — see docs/pagination.md and CLAUDE.md's note on
      // the pagination programme.
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),
};
