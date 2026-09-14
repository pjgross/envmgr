import api from './api';
import type { CloseoutRead } from '../types/closeout';
import type { ReleaseResponse } from '../types/release';

export const closeoutService = {
  get: (releaseId: number): Promise<CloseoutRead> =>
    api.get(`/releases/${releaseId}/closeout`).then((r) => r.data),
  declareStable: (releaseId: number, note?: string): Promise<ReleaseResponse> =>
    api.post(`/releases/${releaseId}/declare-stable`, { note: note ?? null }).then((r) => r.data),
  withdrawStable: (releaseId: number): Promise<ReleaseResponse> =>
    api.delete(`/releases/${releaseId}/declare-stable`).then((r) => r.data),
  confirmHandover: (releaseId: number, note?: string): Promise<ReleaseResponse> =>
    api.post(`/releases/${releaseId}/confirm-handover`, { note: note ?? null }).then((r) => r.data),
  withdrawHandover: (releaseId: number): Promise<ReleaseResponse> =>
    api.delete(`/releases/${releaseId}/confirm-handover`).then((r) => r.data),
};
