import api from './api';
import type {
  ReleaseEventTypeResponse,
  ReleaseEventTypeCreatePayload,
  ReleaseEventTypeUpdatePayload,
} from '../types/releaseEvent';

export const releaseEventTypeService = {
  list: (): Promise<ReleaseEventTypeResponse[]> =>
    api.get('/release-event-types').then((r) => r.data),

  get: (id: number): Promise<ReleaseEventTypeResponse> =>
    api.get(`/release-event-types/${id}`).then((r) => r.data),

  create: (data: ReleaseEventTypeCreatePayload): Promise<ReleaseEventTypeResponse> =>
    api.post('/release-event-types', data).then((r) => r.data),

  update: (id: number, data: ReleaseEventTypeUpdatePayload): Promise<ReleaseEventTypeResponse> =>
    api.put(`/release-event-types/${id}`, data).then((r) => r.data),

  remove: (id: number): Promise<void> =>
    api.delete(`/release-event-types/${id}`).then(() => undefined),
};
