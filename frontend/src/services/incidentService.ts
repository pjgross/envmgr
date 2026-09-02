import api from './api';
import type { Paged } from '../types/pagination';
import type {
  IncidentListRow, IncidentDetail, IncidentCreate, IncidentUpdate, IncidentPirCitation,
} from '../types/incident';

export const incidentService = {
  list: (params: Record<string, unknown> = {}): Promise<Paged<IncidentListRow>> =>
    api.get<IncidentListRow[]>('/incidents', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),
  get: (id: number) => api.get<IncidentDetail>(`/incidents/${id}`).then((r) => r.data),
  create: (data: IncidentCreate) => api.post<IncidentDetail>('/incidents', data).then((r) => r.data),
  update: (id: number, data: IncidentUpdate) => api.patch<IncidentDetail>(`/incidents/${id}`, data).then((r) => r.data),
  transition: (id: number, to_state: string) =>
    api.post<IncidentDetail>(`/incidents/${id}/transition`, { to_state }).then((r) => r.data),
  remove: (id: number) => api.delete(`/incidents/${id}`).then((r) => r.data),

  /** Cite this incident on a release's PIR, creating the PIR, the finding and
   *  its actions if they do not exist — ONE call, because `get_db` commits per
   *  request and three calls would leave a PIR behind when the second failed. */
  citeOnPir: (
    incidentId: number,
    data: {
      release_id: number;
      finding_id?: number;
      new_finding?: {
        title: string; detail?: string | null; root_cause?: string | null;
        actions?: { title: string; owner_id?: number | null; due_date?: string | null }[];
      };
      note?: string | null;
    },
  ) => api.post<IncidentPirCitation[]>(`/incidents/${incidentId}/pir-citation`, data)
        .then((r) => r.data),
};
