import api from './api';
import type {
  ReleaseTemplateResponse,
  ReleaseTemplateCreatePayload,
  ReleaseTemplateUpdatePayload,
  ReleaseTemplateInstantiatePayload,
} from '../types/releaseTemplate';
import type { ReleaseResponse } from '../types/release';

export const releaseTemplateService = {
  list: (): Promise<ReleaseTemplateResponse[]> =>
    api.get('/release-templates').then((r) => r.data),

  get: (id: number): Promise<ReleaseTemplateResponse> =>
    api.get(`/release-templates/${id}`).then((r) => r.data),

  create: (data: ReleaseTemplateCreatePayload): Promise<ReleaseTemplateResponse> =>
    api.post('/release-templates', data).then((r) => r.data),

  update: (id: number, data: ReleaseTemplateUpdatePayload): Promise<ReleaseTemplateResponse> =>
    api.put(`/release-templates/${id}`, data).then((r) => r.data),

  remove: (id: number): Promise<void> =>
    api.delete(`/release-templates/${id}`).then(() => undefined),

  instantiate: (id: number, data: ReleaseTemplateInstantiatePayload): Promise<ReleaseResponse> =>
    api.post(`/release-templates/${id}/instantiate`, data).then((r) => r.data),
};
