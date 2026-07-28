import api from './api';
import type { IncidentListRow, IncidentDetail, IncidentCreate, IncidentUpdate } from '../types/incident';

export const incidentService = {
  list: (params: Record<string, unknown> = {}) =>
    api.get<IncidentListRow[]>('/incidents', { params }).then((r) => r.data),
  get: (id: number) => api.get<IncidentDetail>(`/incidents/${id}`).then((r) => r.data),
  create: (data: IncidentCreate) => api.post<IncidentDetail>('/incidents', data).then((r) => r.data),
  update: (id: number, data: IncidentUpdate) => api.patch<IncidentDetail>(`/incidents/${id}`, data).then((r) => r.data),
  transition: (id: number, to_state: string) =>
    api.post<IncidentDetail>(`/incidents/${id}/transition`, { to_state }).then((r) => r.data),
  remove: (id: number) => api.delete(`/incidents/${id}`).then((r) => r.data),
};
