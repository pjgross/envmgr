import api from './api';
import type {
  Attestation,
  AttestationCreate,
  CancelRequest,
  Decommission,
  DecommissionCreate,
  DecommissionState,
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
