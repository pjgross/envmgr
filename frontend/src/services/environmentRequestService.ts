import api from './api';
import type {
  AllowedTransition,
  EnvironmentHandoverUpdate,
  EnvironmentRequestCreate,
  EnvironmentRequestResponse,
  EnvironmentRequestUpdate,
  WelcomePack,
} from '../types/environmentRequest';
import type { EnvironmentResponse } from '../types/environment';
import type { Paged } from '../types/pagination';

export const environmentRequestService = {
  listRequests: (params?: {
    limit?: number;
    offset?: number;
    sort_by?: string;
    sort_dir?: 'asc' | 'desc';
    status?: string;
    kind?: string;
    environment_id?: number;
    mine?: boolean;
    actionable?: boolean;
  }): Promise<Paged<EnvironmentRequestResponse>> =>
    api.get<EnvironmentRequestResponse[]>('/environment-requests', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),

  getRequest: (id: number): Promise<EnvironmentRequestResponse> =>
    api.get(`/environment-requests/${id}`).then((r) => r.data),

  createRequest: (data: EnvironmentRequestCreate): Promise<EnvironmentRequestResponse> =>
    api.post('/environment-requests', data).then((r) => r.data),

  updateRequest: (
    id: number,
    data: EnvironmentRequestUpdate
  ): Promise<EnvironmentRequestResponse> =>
    api.patch(`/environment-requests/${id}`, data).then((r) => r.data),

  // No `notes` parameter: the backend's EnvironmentRequestTransition body is
  // `{to_state}` only — there is no history table for this entity, so a
  // `notes` value sent here would be accepted and silently discarded.
  transition: (id: number, toState: string): Promise<EnvironmentRequestResponse> =>
    api
      .post(`/environment-requests/${id}/transition`, { to_state: toState })
      .then((r) => r.data),

  allowedTransitions: (id: number): Promise<AllowedTransition[]> =>
    api.get(`/environment-requests/${id}/allowed-transitions`).then((r) => r.data),

  getWelcomePack: (id: number): Promise<WelcomePack> =>
    api.get(`/environment-requests/${id}/welcome-pack`).then((r) => r.data),

  updateHandover: (
    environmentId: number,
    data: EnvironmentHandoverUpdate
  ): Promise<EnvironmentResponse> =>
    api.patch(`/environments/${environmentId}/handover`, data).then((r) => r.data),
};
