import api from './api';
import type {
  AllowedTransition,
  ChangeRequestResponse,
  ChangeRequestDetailResponse,
  ChangeRequestCreatePayload,
  ChangeRequestUpdatePayload,
  ChangeRequestTransitionPayload,
  ChangeRequestListFilters,
  PreviewOutageConflictsPayload,
  PreviewOutageConflictsResponse,
} from '../types/changeRequest';

export const changeRequestService = {
  list: (filters: ChangeRequestListFilters = {}): Promise<ChangeRequestResponse[]> =>
    api.get('/change-requests', { params: filters }).then((r) => r.data),

  get: (id: number): Promise<ChangeRequestDetailResponse> =>
    api.get(`/change-requests/${id}`).then((r) => r.data),

  create: (data: ChangeRequestCreatePayload): Promise<ChangeRequestResponse> =>
    api.post('/change-requests', data).then((r) => r.data),

  update: (id: number, data: ChangeRequestUpdatePayload): Promise<ChangeRequestResponse> =>
    api.patch(`/change-requests/${id}`, data).then((r) => r.data),

  transition: (
    id: number,
    data: ChangeRequestTransitionPayload
  ): Promise<ChangeRequestResponse> =>
    api.post(`/change-requests/${id}/transition`, data).then((r) => r.data),

  getAllowedTransitions: (id: number): Promise<AllowedTransition[]> =>
    api.get(`/change-requests/${id}/allowed-transitions`).then((r) => r.data),

  remove: (id: number): Promise<void> =>
    api.delete(`/change-requests/${id}`).then(() => undefined),

  previewOutageConflicts: (
    data: PreviewOutageConflictsPayload
  ): Promise<PreviewOutageConflictsResponse> =>
    api.post('/change-requests/preview-outage-conflicts', data).then((r) => r.data),
};
