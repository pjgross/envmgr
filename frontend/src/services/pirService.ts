import api from './api';
import type { Paged } from '../types/pagination';
import type {
  PIR, PIRWrite, PirAction, PirActionRow, PirActionWrite, PirCitation, PirFinding,
  PirFindingWrite,
} from '../types/pir';

export const pirService = {
  getForRelease: (releaseId: number) =>
    api.get<PIR | null>(`/releases/${releaseId}/pir`).then((r) => r.data),
  create: (releaseId: number, data: PIRWrite) =>
    api.post<PIR>(`/releases/${releaseId}/pir`, data).then((r) => r.data),
  update: (releaseId: number, data: PIRWrite) =>
    api.patch<PIR>(`/releases/${releaseId}/pir`, data).then((r) => r.data),
  remove: (releaseId: number) => api.delete(`/releases/${releaseId}/pir`).then((r) => r.data),

  createFinding: (releaseId: number, data: PirFindingWrite) =>
    api.post<PirFinding>(`/releases/${releaseId}/pir/findings`, data).then((r) => r.data),
  updateFinding: (releaseId: number, findingId: number, data: PirFindingWrite) =>
    api.patch<PirFinding>(`/releases/${releaseId}/pir/findings/${findingId}`, data)
      .then((r) => r.data),
  deleteFinding: (releaseId: number, findingId: number) =>
    api.delete(`/releases/${releaseId}/pir/findings/${findingId}`).then((r) => r.data),

  // Actions are addressed THROUGH their finding, never by id alone: the server
  // refuses an action id that does not belong to the finding in the path, so a
  // shortened URL would 422 rather than quietly editing the right row.
  createAction: (releaseId: number, findingId: number, data: PirActionWrite) =>
    api.post<PirAction>(`/releases/${releaseId}/pir/findings/${findingId}/actions`, data)
      .then((r) => r.data),
  updateAction: (releaseId: number, findingId: number, actionId: number, data: PirActionWrite) =>
    api.patch<PirAction>(
      `/releases/${releaseId}/pir/findings/${findingId}/actions/${actionId}`, data)
      .then((r) => r.data),
  deleteAction: (releaseId: number, findingId: number, actionId: number) =>
    api.delete(`/releases/${releaseId}/pir/findings/${findingId}/actions/${actionId}`)
      .then((r) => r.data),

  // The citation is keyed on (finding, incident) — there is no citation id to
  // hold, and re-citing updates the note rather than adding a row.
  citeIncident: (releaseId: number, findingId: number,
                 data: { incident_id: number; note?: string | null }) =>
    api.post<PirCitation[]>(`/releases/${releaseId}/pir/findings/${findingId}/incidents`, data)
      .then((r) => r.data),
  unciteIncident: (releaseId: number, findingId: number, incidentId: number) =>
    api.delete(`/releases/${releaseId}/pir/findings/${findingId}/incidents/${incidentId}`)
      .then((r) => r.data),

  listActions: (params: Record<string, unknown> = {}): Promise<Paged<PirActionRow>> =>
    api.get<PirActionRow[]>('/pir-actions', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),
};
