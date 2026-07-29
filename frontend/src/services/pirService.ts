import api from './api';
import type { PIR, PIRWrite } from '../types/pir';

export const pirService = {
  getForRelease: (releaseId: number) =>
    api.get<PIR | null>(`/releases/${releaseId}/pir`).then((r) => r.data),
  create: (releaseId: number, data: PIRWrite) =>
    api.post<PIR>(`/releases/${releaseId}/pir`, data).then((r) => r.data),
  update: (releaseId: number, data: PIRWrite) =>
    api.patch<PIR>(`/releases/${releaseId}/pir`, data).then((r) => r.data),
  remove: (releaseId: number) => api.delete(`/releases/${releaseId}/pir`).then((r) => r.data),
};
