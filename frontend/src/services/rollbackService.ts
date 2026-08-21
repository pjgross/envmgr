import api from './api';
import type {
  RollbackPlanResponse,
  RollbackPlanCreate,
  RehearsalResponse,
  RehearsalCreate,
  RollbackAuthorisationResponse,
  RollbackAuthorisationCreate,
  RollbackPolicy,
  RollbackPolicyUpdate,
} from '../types/rollback';

// No pagination on any of these: each is a per-release or per-system
// collection bounded by that entity's own component count or how many times
// a rollback is actually rehearsed/authorised — same reasoning the backend
// routes carry (see app/api/v1/releases.py's rollback-plans/
// rollback-authorisations comments and app/api/v1/systems.py's
// rollback-rehearsals comment).
export const rollbackService = {
  // --- Rollback plans (per release, one per changing component) ---
  listPlans: (releaseId: number): Promise<RollbackPlanResponse[]> =>
    api.get(`/releases/${releaseId}/rollback-plans`).then((r) => r.data),

  // PUT is an upsert, keyed on (release_id, system_id) server-side.
  upsertPlan: (
    releaseId: number,
    data: RollbackPlanCreate
  ): Promise<RollbackPlanResponse> =>
    api.put(`/releases/${releaseId}/rollback-plans`, data).then((r) => r.data),

  agreePlan: (releaseId: number, planId: number): Promise<RollbackPlanResponse> =>
    api.post(`/releases/${releaseId}/rollback-plans/${planId}/agree`).then((r) => r.data),

  deletePlan: (releaseId: number, planId: number): Promise<void> =>
    api.delete(`/releases/${releaseId}/rollback-plans/${planId}`).then(() => undefined),

  // --- Rollback authorisations (per release; C4 records, never refuses) ---
  listAuthorisations: (releaseId: number): Promise<RollbackAuthorisationResponse[]> =>
    api.get(`/releases/${releaseId}/rollback-authorisations`).then((r) => r.data),

  recordAuthorisation: (
    releaseId: number,
    data: RollbackAuthorisationCreate
  ): Promise<RollbackAuthorisationResponse> =>
    api.post(`/releases/${releaseId}/rollback-authorisations`, data).then((r) => r.data),

  // --- Rehearsals (per system) ---
  listRehearsals: (systemId: number): Promise<RehearsalResponse[]> =>
    api.get(`/systems/${systemId}/rollback-rehearsals`).then((r) => r.data),

  recordRehearsal: (
    systemId: number,
    data: RehearsalCreate
  ): Promise<RehearsalResponse> =>
    api.post(`/systems/${systemId}/rollback-rehearsals`, data).then((r) => r.data),

  // --- Policy (per tenant; GET open to any member, PUT Admin-only) ---
  getPolicy: (): Promise<RollbackPolicy> =>
    api.get('/tenant/rollback-policy').then((r) => r.data),

  updatePolicy: (data: RollbackPolicyUpdate): Promise<RollbackPolicy> =>
    api.put('/tenant/rollback-policy', data).then((r) => r.data),
};
